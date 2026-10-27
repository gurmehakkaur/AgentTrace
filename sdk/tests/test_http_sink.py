"""HttpSink against a throwaway local HTTP server: paths, bodies, auth header, retries."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agenttrace_sdk import HttpSink, HttpSinkError


class Recorder(BaseHTTPRequestHandler):
    seen: list[dict] = []
    fail_first: int = 0

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append({"path": self.path, "auth": self.headers["Authorization"], "body": body})
        if type(self).fail_first > 0:
            type(self).fail_first -= 1
            code = 503
        else:
            code = 401 if self.headers["Authorization"] != "Bearer at_live_good" else 200
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b'{"detail":"nope"}' if code != 200 else b"{}")

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    Recorder.seen, Recorder.fail_first = [], 0
    httpd = HTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def run(coro):
    return asyncio.run(coro)


def test_sink_posts_run_steps_and_finish_with_the_bearer_key(server):
    sink = HttpSink(server, "at_live_good")

    async def go():
        await sink.start_run({"id": "run12345", "workflow": "w"})
        await sink.add_steps("run12345", [{"idx": 1}])
        await sink.finish_run("run12345", "ok", "fail", {"a": 1})

    run(go())
    assert [(r["path"], r["auth"]) for r in Recorder.seen] == [
        ("/v1/runs", "Bearer at_live_good"),
        ("/v1/runs/run12345/steps", "Bearer at_live_good"),
        ("/v1/runs/run12345/finish", "Bearer at_live_good"),
    ]
    assert Recorder.seen[1]["body"] == {"steps": [{"idx": 1}]}
    assert Recorder.seen[2]["body"] == {"status": "ok", "outcome": "fail", "oracle_detail": {"a": 1}}


def test_server_errors_are_retried_then_succeed(server):
    Recorder.fail_first = 2
    run(HttpSink(server, "at_live_good", retries=2).start_run({"id": "x"}))
    assert len(Recorder.seen) == 3


def test_client_errors_raise_without_retry_and_never_leak_the_key(server):
    with pytest.raises(HttpSinkError, match="401") as err:
        run(HttpSink(server, "at_live_wrongkey").start_run({"id": "x"}))
    assert len(Recorder.seen) == 1
    assert "wrongkey" not in str(err.value)
