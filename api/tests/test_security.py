"""Phase 13: the controls that protect data and spend. Deleting a run and everything derived from
it (admin only, audited, memory forgotten), the audit log, per-user daily and per-minute limits,
size limits, and redaction at ingest."""

import asyncio
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_key
from app.main import app
from app.runtime import get_runtime
from app.security.limits import MAX_BODY_BYTES, MAX_FIELD_CHARS, SlidingWindowLimiter, clamp_strings
from test_experiments import FakeLLM, FixtureTools
from test_fork import FIXED_PLAN, WS, record
from test_memory import mem, verified_experiment  # noqa: F401  (fixture re-export)
from test_rca import FakeModel, cand, tool_use
from test_renewal_brief import APPROVE, BUGGY_PLAN, draft

KEY = "at_live_SECURITYSECURITYSECURITYSECURITY"
API_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(store, login):
    app.dependency_overrides[get_runtime] = lambda: (FakeLLM(), FixtureTools())
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.pop(get_runtime, None)


@pytest.fixture
def failed_run(store):
    run_id = record(BUGGY_PLAN, "No open tickets.", draft(0), APPROVE)
    store.runs[run_id].update(outcome="fail", oracle_detail={"open_tickets_ok": False})
    return run_id


def launch(client, run_id, n=1):
    return client.post("/v1/experiments", json={"run_id": run_id, "fork_node_run_idx": 1, "edit": FIXED_PLAN, "n": n})


def actions(store):
    return [(a["action"], a["actor"], a["workspace"]) for a in store.audit]


# --- deleting a run --------------------------------------------------------------------------

def build_tree(store, mem, failed_run):
    """A parent run with fork runs, an experiment, a root-cause report and a remembered pattern,
    plus an unrelated run in the same workspace and one in another workspace."""
    verified_experiment(failed_run)  # control fails, treatment passes: remembered in the fake memory
    asyncio.run(store.create_rca_report(WS, "r1", {"run": failed_run, "lineage": [1], "created_at": "2026-01-01T00:00:00Z",
                                                   "model": "m", "tokens_in": 1, "tokens_out": 1, "candidates": []}))
    keep_same_ws = record(BUGGY_PLAN, "s", draft(0), APPROVE)
    keep_other_ws = record(BUGGY_PLAN, "s", draft(0), APPROVE, ws="ws-other")
    return keep_same_ws, keep_other_ws


def test_an_admin_deletes_a_run_with_its_forks_experiments_reports_and_memory(client, store, mem, failed_run, login):
    keep_same, keep_other = build_tree(store, mem, failed_run)
    fork_ids = {f["fork_run"] for f in store.forks if f["parent"] == failed_run}
    assert fork_ids and mem.items and store.experiments and store.rca_reports

    login("ws-a", "admin")
    resp = client.delete(f"/v1/runs/{failed_run}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"]["runs"] == 1 + len(fork_ids) and body["deleted"]["experiments"] == 1
    assert body["deleted"]["rca_reports"] == 1 and body["deleted"]["steps"] > 0
    assert body["memory"] == {"items_forgotten": 1, "scopes_not_forgotten": 0}

    gone = {failed_run, *fork_ids}
    assert not gone & set(store.runs) and not [k for k in store.steps if k[0] in gone]
    assert store.experiments == {} and store.tested == [] and store.forks == [] and store.rca_reports == []
    assert mem.items == []  # the remembered pattern derived from the run is forgotten
    assert keep_same in store.runs and keep_other in store.runs  # nothing else was touched
    assert ("run.delete", "user_1", "ws-a") in actions(store)


def test_a_member_cannot_delete_and_nothing_changes(client, store, failed_run, login):
    login("ws-a", "member")
    assert client.delete(f"/v1/runs/{failed_run}").status_code == 403
    assert failed_run in store.runs and not [a for a in store.audit if a["action"] == "run.delete"]


def test_another_workspaces_admin_gets_404_and_a_logged_out_caller_401(client, store, failed_run, login):
    login("ws-b", "admin")
    assert client.delete(f"/v1/runs/{failed_run}").status_code == 404
    assert failed_run in store.runs
    from app.auth import get_principal
    app.dependency_overrides.pop(get_principal)
    assert client.delete(f"/v1/runs/{failed_run}").status_code == 401


def test_deletion_is_refused_when_it_cannot_be_audited(client, store, failed_run, login):
    login("ws-a", "admin")
    store.fail_audit = True
    assert client.delete(f"/v1/runs/{failed_run}").status_code == 500
    assert failed_run in store.runs  # no audit record, no deletion


def test_a_memory_outage_does_not_block_deletion_but_is_recorded(client, store, mem, failed_run, login):
    build_tree(store, mem, failed_run)
    mem.fail = True
    login("ws-a", "admin")
    body = client.delete(f"/v1/runs/{failed_run}").json()
    assert failed_run not in store.runs
    assert body["memory"] == {"items_forgotten": 0, "scopes_not_forgotten": 1}
    assert "run.delete.memory_incomplete" in [a["action"] for a in store.audit]


# --- the audit log ---------------------------------------------------------------------------

def test_launching_experiments_and_analyses_is_audited_and_admins_can_read_the_log(client, store, failed_run, login):
    login("ws-a", "admin")
    exp = launch(client, failed_run).json()["id"]
    entry = next(a for a in store.audit if a["action"] == "experiment.launch")
    assert entry["target"] == exp and entry["actor"] == "user_1" and entry["workspace"] == "ws-a"
    assert entry["detail"] == {"parent_run": failed_run, "fork_node_run_idx": 1, "n": 1, "edit_keys": ["plan"]}

    log = client.get("/v1/audit").json()
    assert [a["action"] for a in log] == ["experiment.launch"]
    login("ws-b", "admin")
    assert client.get("/v1/audit").json() == []  # another workspace's admin sees none of it
    login("ws-a", "member")
    assert client.get("/v1/audit").status_code == 403


def test_an_audit_failure_does_not_block_a_launch(client, store, failed_run, login):
    login("ws-a", "member")
    store.fail_audit = True
    assert launch(client, failed_run).status_code == 202


# --- per-user daily cap and per-minute rate limit -------------------------------------------

def test_the_daily_cap_blocks_the_next_launch_with_a_friendly_429(client, store, failed_run, login, monkeypatch):
    monkeypatch.setenv("DAILY_EXPERIMENTS_PER_USER", "2")
    login("ws-a", "member", "user_1")
    assert [launch(client, failed_run).status_code for _ in range(2)] == [202, 202]

    resp = launch(client, failed_run)
    assert resp.status_code == 429 and "Daily experiment limit reached (2 per user per day" in resp.json()["detail"]
    assert int(resp.headers["retry-after"]) > 0

    login("ws-a", "member", "user_2")  # the cap is per user
    assert launch(client, failed_run).status_code == 202


def test_only_todays_experiments_count_against_the_cap(client, store, failed_run, login, monkeypatch):
    monkeypatch.setenv("DAILY_EXPERIMENTS_PER_USER", "1")
    login("ws-a", "member")
    assert launch(client, failed_run).status_code == 202
    assert launch(client, failed_run).status_code == 429
    for e in store.experiments.values():  # pretend the first one was yesterday's
        e["created_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert launch(client, failed_run).status_code == 202


def test_launches_are_rate_limited_per_user_per_minute(client, store, failed_run, login, monkeypatch):
    monkeypatch.setenv("DAILY_EXPERIMENTS_PER_USER", "100")
    login("ws-a", "member", "user_1")
    assert [launch(client, failed_run).status_code for _ in range(6)] == [202] * 6
    blocked = launch(client, failed_run)
    assert blocked.status_code == 429 and "Too many requests" in blocked.json()["detail"]
    assert int(blocked.headers["retry-after"]) >= 1
    login("ws-a", "member", "user_2")
    assert launch(client, failed_run).status_code == 202


def test_root_cause_analyses_are_rate_limited_too(client, store, failed_run, login):
    login("ws-a", "member")
    app.dependency_overrides[get_runtime] = lambda: (FakeModel(*[[tool_use({"candidates": [cand()]})] for _ in range(7)]), None)
    assert [client.post(f"/v1/runs/{failed_run}/rca").status_code for _ in range(6)] == [200] * 6
    assert client.post(f"/v1/runs/{failed_run}/rca").status_code == 429


def test_the_limiter_window_slides():
    now = [0.0]
    limiter = SlidingWindowLimiter(max_calls=2, window_s=10, clock=lambda: now[0])
    limiter.check("u"); limiter.check("u")
    with pytest.raises(Exception) as err:
        limiter.check("u")
    assert err.value.status_code == 429
    now[0] = 10.5  # the first two calls have aged out
    limiter.check("u")


# --- size limits and ingest redaction --------------------------------------------------------

def test_clamp_truncates_long_text_keeps_a_hash_and_leaves_the_rest_alone():
    long = "a" * (MAX_FIELD_CHARS + 500)
    out = clamp_strings({"x": long, "nested": [{"y": long}], "short": "ok", "n": 3, "none": None})
    assert out["x"].startswith("a" * MAX_FIELD_CHARS) and "truncated: 33268 chars, sha256 " in out["x"]
    assert out["x"] == out["nested"][0]["y"] and out["short"] == "ok" and out["n"] == 3 and out["none"] is None


@pytest.fixture
def ingest(store):
    store.keys[hash_key(KEY)] = "ws-a"
    return {"Authorization": f"Bearer {KEY}"}


def step(**over):
    return {"idx": 1, "node_run_idx": 1, "agent": "planner", "kind": "llm", "origin": "recorded", **over}


def test_ingest_truncates_huge_payload_fields(client, store, ingest):
    client.post("/v1/runs", headers=ingest, json={"id": "run0000000000001", "workflow": "w", "started_at": "t"})
    huge = "z" * 100_000
    client.post("/v1/runs/run0000000000001/steps", headers=ingest, json={"steps": [step(output={"text": huge}, agent="planner")]})
    stored = store.steps[("run0000000000001", 1)]
    assert len(stored["output"]["text"]) < 33_500 and "sha256" in stored["output"]["text"] and stored["agent"] == "planner"


def test_oversized_request_bodies_are_refused_with_413(client, ingest):
    resp = client.post("/v1/runs/run0000000000001/steps", headers=ingest, content=b"x" * (MAX_BODY_BYTES + 1))
    assert resp.status_code == 413


def test_ingest_stores_an_email_an_api_key_and_a_bearer_token_redacted(client, store, ingest):
    client.post("/v1/runs", headers=ingest, json={"id": "run0000000000002", "workflow": "w", "started_at": "t"})
    prompt = ("contact jane.doe@acme.com, use key sk-ant-api03-PLANTEDsecret0123456789_abcDEF "
              "and header Authorization: Bearer eyJhbGciOi123456789abcdef")
    client.post("/v1/runs/run0000000000002/steps", headers=ingest, json={"steps": [step(input={"messages": [{"content": prompt}]})]})
    stored = str(store.steps[("run0000000000002", 1)])
    assert "jane.doe" not in stored and "PLANTEDsecret" not in stored and "eyJhbGciOi123456789" not in stored
    assert stored.count("[REDACTED:") >= 3
    assert {r["type"] for r in store.steps[("run0000000000002", 1)]["redactions"]} >= {"email", "api_key", "bearer"}


# --- production hardening --------------------------------------------------------------------

def _status_in_env(env: str, path: str) -> int:
    code = ("from fastapi.testclient import TestClient; from app.main import app; "
            f"print(TestClient(app).get('{path}').status_code)")
    out = subprocess.run([sys.executable, "-c", code], cwd=API_DIR, capture_output=True, text=True,
                         env={**__import__("os").environ, "ENV": env})
    return int(out.stdout.strip().splitlines()[-1])


def test_interactive_api_docs_exist_in_dev_but_not_in_production():
    assert _status_in_env("dev", "/docs") == 200
    assert [_status_in_env("prod", p) for p in ("/docs", "/redoc", "/openapi.json")] == [404, 404, 404]
