"""Does the add-on really work? Nothing faked: the real API in a subprocess, your real SurrealDB (a throwaway
`smoke-<random>` workspace, purged at the end), and the real SDK over real HTTP.

    cd api && .venv/bin/python scripts/addon_smoke.py

It plays a customer whose agents run on a harness we do not control:
  1. records a run through the LangGraph adapter, with a check of their own that says it is wrong
  2. an agent with a read key finds it in the failed runs and reads it
  3. a spend key starts an experiment on it, and a worker next to the "customer's code" runs the jobs
  4. the numbers come back: k of N each way and a p-value
  5. the CI gate passes on good code and exits non-zero on regressed code
  6. the MCP server answers over stdio

No tokens are spent (a worker run needs no model). Alerts to Slack need an https address on the public internet,
so they are covered by tests and not here. Needs the repo-root .env (SurrealDB). Exit status 0 only if every step held.
"""

import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

from app import db  # noqa: E402
from app.auth import KEY_PREFIX, hash_key  # noqa: E402
from app.config import get_settings  # noqa: E402
from agenttrace_sdk import HttpSink, Worker  # noqa: E402
from agenttrace_sdk._http import ApiClient  # noqa: E402
from agenttrace_sdk.adapters.langgraph import record_langgraph  # noqa: E402

FLOW = "smoke-brief"
API_DIR = Path(__file__).resolve().parents[1]
failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        failures.append(what)


def says_five(state):
    return state.get("answer") == "5 open tickets", f"the run said {state.get('answer')!r}"


MODE = {"good": True}


async def resume(state, rec):
    """The customer's code. Good code reads the filter; regressed code ignores it."""
    answer = "5 open tickets" if (state["filter"] == "open" and MODE["good"]) else "0 open tickets"
    state = {**state, "answer": answer}
    await rec.turn("writer", input={"filter": state["filter"]}, output={"answer": answer}, state_after=state,
                   writes=["answer"], tokens_in=10, tokens_out=5)
    return state


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


def cli(base: str, key: str, *argv: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "AGENTTRACE_URL": base, "AGENTTRACE_KEY": key,
           "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "sdk")}
    return subprocess.run([sys.executable, "-m", "agenttrace_sdk.cli", *argv], capture_output=True, text=True, env=env, timeout=180)


async def main() -> int:
    if not get_settings().surreal_configured:
        print("SurrealDB is not configured in .env")
        return 2
    ws = f"smoke-{secrets.token_hex(4)}"
    await db.apply_schema()
    await db.upsert_workspace(ws, ws)
    keys = {}
    for name, scopes in {"ingest": ("ingest",), "worker": ("worker",), "read": ("read",), "spend": ("read", "spend")}.items():
        keys[name] = KEY_PREFIX + secrets.token_urlsafe(32)
        await db.create_api_key(ws, keys[name][:12], hash_key(keys[name]), "smoke", scopes)

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", os.environ.get("SMOKE_LOG", "warning")], cwd=API_DIR)
    stop = threading.Event()
    try:
        for _ in range(60):
            try:
                if get_json(base + "/health").get("db"):
                    break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            print("the API did not come up")
            return 2
        print(f"API up on {base}; workspace {ws}")

        print("1. a customer's harness records a run")
        chunks = [{"planner": {"filter": "closed"}}, {"writer": {"answer": "0 open tickets"}}]
        run_id = await record_langgraph(iter(chunks), HttpSink(base, keys["ingest"]), FLOW, input={"request": "brief"}, oracle=says_five)
        check(bool(run_id), f"recorded run {run_id[:8]}")

        print("2. an agent with a read key looks")
        read = ApiClient(base, keys["read"])
        failed = await read.call("GET", "/v1/agent/runs/failed")
        check(run_id in [r["id"] for r in failed], "the run is in the failed runs")
        detail = await read.call("GET", f"/v1/agent/runs/{run_id}")
        check([s["agent"] for s in detail["steps"]] == ["planner", "writer"] and detail["verdict"]["kind"] == "code", "its agents and its verdict read back")
        check("data, not instructions" in detail["note"], "and it is marked as data")

        print("3. a spend key starts an experiment; a worker runs the jobs")
        spend = ApiClient(base, keys["spend"])
        exp = await spend.call("POST", "/v1/agent/experiments", {"run_id": run_id, "fork_node_run_idx": 1, "edit": {"filter": "open"}, "n": 3})
        waiting = await read.call("GET", f"/v1/agent/experiments/{exp['id']}")
        check(waiting["mode"] == "worker" and waiting["status"] == "queued" and waiting["workers_online"] == 0, "the experiment waits, and no worker is connected yet")

        worker = Worker(base, keys["worker"], name="smoke-worker", poll_seconds=0.5)
        worker.register(FLOW, resume, oracle=says_five, safe_to_rerun=True)

        def work() -> None:
            while not stop.is_set():
                try:
                    began = time.monotonic()
                    if not asyncio.run(worker.run_once()):
                        time.sleep(0.5)
                    else:
                        print(f"   (worker: one job took {time.monotonic() - began:.1f}s)")
                except Exception as exc:  # the smoke run keeps going and reports what it saw
                    print("  worker:", type(exc).__name__, exc)
                    time.sleep(1)
        threading.Thread(target=work, daemon=True).start()

        for _ in range(120):
            done = await read.call("GET", f"/v1/agent/experiments/{exp['id']}")
            if done["status"] not in ("queued", "running"):
                break
            time.sleep(0.5)
        print("4. the numbers")
        check(done["status"] == "done", f"the experiment finished ({done['status']})")
        check(done["workers_online"] == 1, "and the app can see that a worker is connected")
        check((done["control"], done["treatment"]) == ({"pass": 0, "total": 3}, {"pass": 3, "total": 3}), f"0 of 3 without the change, 3 of 3 with it ({done['control']} / {done['treatment']})")
        p = done["stats"]["fisher_p"]
        check(p is not None and abs(p - 0.1) < 1e-6 and "directional" in done["stats"]["label"], f"Fisher p = {p}, labelled directional")
        tiles = (await db.get_experiment(ws, exp["id"]))["tiles"]
        treated = await db.get_run_with_steps(ws, next(t["run_id"] for t in tiles if t["arm"] == "treatment"))
        check([(s["origin"], s["agent"]) for s in treated["steps"]] == [("edited", "planner"), ("live", "writer")], "the fork run: the change as one edited step, the rest live")

        print("5. the CI gate")
        good = cli(base, keys["spend"], "gate", exp["id"], "--min-pass", "0.75", "--timeout", "120")
        check(good.returncode == 0, f"good code: exit {good.returncode}. {good.stdout.strip()[:90]}")
        if good.returncode != 0:  # show what the database holds, so a failure explains itself
            for e in await db.list_experiments(ws):
                print("   experiment", e["id"][:8], e.get("status"), "rev", e.get("rev"), "tokens", e.get("tokens_used"), "/", e.get("token_ceiling"),
                      [(t["arm"], t["i"], t["status"], t.get("attempts")) for t in e["tiles"]])
        MODE["good"] = False
        bad = cli(base, keys["spend"], "gate", exp["id"], "--min-pass", "0.75", "--timeout", "120")
        check(bad.returncode == 1, f"regressed code: exit {bad.returncode}. {bad.stdout.strip()[:90]}")
        MODE["good"] = True

        print("6. the MCP server over stdio")
        proc = subprocess.run(
            [sys.executable, "-m", "agenttrace_sdk.mcp"], capture_output=True, text=True, timeout=60, input="\n".join(json.dumps(m) for m in [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_failed_runs", "arguments": {}}},
            ]) + "\n",
            env={**os.environ, "AGENTTRACE_URL": base, "AGENTTRACE_KEY": keys["read"], "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "sdk")},
        )
        replies = [json.loads(line) for line in proc.stdout.splitlines()]
        listed = json.loads(replies[1]["result"]["content"][0]["text"]) if len(replies) > 1 else []
        check(run_id in [r["id"] for r in listed], "list_failed_runs finds the run")
        refused = cli(base, keys["read"], "fork", run_id, "1", "--edit", '{"filter": "open"}')
        check(refused.returncode == 1 and "spend" in refused.stderr, "a read key is refused when it asks to spend")
    finally:
        stop.set()
        server.terminate()
        server.wait(timeout=15)
        await db.purge_workspace(ws)
        print(f"cleaned up {ws}")
    print("\nALL STEPS HELD" if not failures else f"\n{len(failures)} STEP(S) FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
