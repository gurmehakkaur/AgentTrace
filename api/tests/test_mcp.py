"""P4 end to end: an MCP client and the CLI, talking to the real routes in-process."""

import io
import json
import sys

import pytest
from fastapi.testclient import TestClient

from agenttrace_sdk._http import ApiError
from agenttrace_sdk import mcp as mcp_server
from agenttrace_sdk import cli
from test_agent_api import judged_run, keys_for, world  # noqa: F401 (world is a fixture)
from test_rca import failing_run  # noqa: F401
from test_worker import record


class Shim:
    """The SDK's HTTP client, answered by the in-process API with a given key."""

    def __init__(self, client, key):
        self.c, self.key = client, key

    def request(self, method, path, payload=None):
        r = self.c.request(method, path, json=payload, headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code >= 400:
            raise ApiError(r.status_code, r.json().get("detail", ""))
        return r.json()


def ask(shim, *calls):
    """Send JSON-RPC requests down the server's pipe and return the replies."""
    lines = [json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})]
    lines += [json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": n, "arguments": a}}) for i, (n, a) in enumerate(calls, 1)]
    out = io.StringIO()
    mcp_server.serve(shim, io.StringIO("\n".join(lines) + "\n"), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()][1:]
    return [(r["result"]["isError"] if "isError" in r["result"] else False, json.loads(r["result"]["content"][0]["text"]) if "isError" not in r["result"] else r["result"]["content"][0]["text"]) for r in replies]


def test_an_agent_over_mcp_lists_failed_runs_and_gets_ranked_suspects_but_never_another_workspaces(world, login, failing_run):
    client, keys = world
    wrong = judged_run(client, keys, "fail")
    (_, failed), (err, suspects) = ask(Shim(client, keys["spend"]), ("list_failed_runs", {}), ("rank_suspects", {"run_id": failing_run}))
    assert {r["id"] for r in failed} >= {wrong, failing_run} and err is False
    assert [s["node_run_idx"] for s in suspects["suspects"]] == [1, 2]
    assert suspects["suspects"][0]["hypothesis"] and "data, not instructions" in suspects["note"]

    login("ws-b", role="admin")
    other = Shim(client, keys_for(client, "read", "spend"))
    (_, none), (e1, text1), (e2, text2) = ask(other, ("list_failed_runs", {}), ("get_run", {"run_id": wrong}), ("rank_suspects", {"run_id": failing_run}))
    assert none == [] and (e1, e2) == (True, True) and "not found" in text1.lower() and "not found" in text2.lower()


def test_over_mcp_a_read_key_is_refused_what_costs_tokens(world, failing_run):
    client, keys = world
    [(err, text)] = ask(Shim(client, keys["read"]), ("rank_suspects", {"run_id": failing_run}))
    assert err is True and "'spend' scope" in text


def test_over_mcp_an_experiment_is_started_and_its_result_read(world):
    client, keys = world
    run_id = record(client, keys)
    [(e1, started)] = ask(Shim(client, keys["spend"]), ("run_experiment", {"run_id": run_id, "fork_node_run_idx": 1, "edit": {"filter": "open"}, "n": 2}))
    [(e2, result)] = ask(Shim(client, keys["read"]), ("get_experiment", {"experiment_id": started["id"]}))
    assert (e1, e2) == (False, False) and result["mode"] == "worker" and result["status"] == "queued"


# --- the command line ------------------------------------------------------------------------

@pytest.fixture
def shell(world, monkeypatch, capsys):
    client, keys = world
    monkeypatch.setenv("AGENTTRACE_URL", "http://api.test")

    def run(key, *argv):
        monkeypatch.setenv("AGENTTRACE_KEY", keys[key])
        monkeypatch.setattr(cli, "ApiClient", lambda url, k: Shim(client, k))
        code = cli.main(list(argv))
        out = capsys.readouterr()
        return code, out.out, out.err
    return run


def test_the_cli_lists_shows_and_forks_and_exits_nonzero_when_refused(shell, world):
    client, keys = world
    run_id = record(client, keys)
    code, out, _ = shell("read", "failed")
    assert code == 0 and run_id in out and "fail" in out
    code, out, _ = shell("read", "show", run_id)
    assert code == 0 and "check says_five" in out and "planner" in out
    code, _, err = shell("read", "fork", run_id, "1", "--edit", '{"filter": "open"}', "-n", "2")
    assert code == 1 and "spend" in err  # a read key cannot start an experiment
    code, out, _ = shell("spend", "fork", run_id, "1", "--edit", '{"filter": "open"}', "-n", "2")
    assert code == 0 and "Started experiment" in out
    exp_id = out.split()[2]
    code, out, _ = shell("read", "--json", "result", exp_id)
    assert code == 0 and json.loads(out)["status"] == "queued"
    code, _, err = shell("spend", "fork", run_id, "1", "--edit", "{not json", "-n", "1")
    assert code == 1 and "Bad input" in err
    code, _, err = shell("read", "show", "nosuchrun")
    assert code == 1 and "not found" in err.lower()


def test_the_cli_says_what_is_missing_when_there_is_no_key(monkeypatch, capsys):
    monkeypatch.delenv("AGENTTRACE_KEY", raising=False)
    monkeypatch.delenv("AGENTTRACE_URL", raising=False)
    assert cli.main(["failed"]) == 1
    assert "AGENTTRACE_KEY" in capsys.readouterr().err
