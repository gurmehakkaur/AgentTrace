"""Connecting an organization: mint a key, send runs with it, import past runs, list the forks.
Offline, against the in-memory store."""

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_key
from app.main import app
from test_experiments import FakeLLM, FixtureTools, run_experiment  # noqa: F401
from test_fork import record
from test_renewal_brief import APPROVE, BUGGY_PLAN, draft


@pytest.fixture
def api(store, login):
    login("ws-a", role="admin")
    with TestClient(app) as client:
        yield client


def test_an_admin_mints_a_key_that_is_shown_once_and_works_for_ingest(api, store):
    resp = api.post("/v1/keys")
    assert resp.status_code == 201
    key = resp.json()["key"]
    assert key.startswith("at_live_") and resp.json()["prefix"] == key[:12]
    # the key opens the ingest door for this workspace only
    run = api.post("/v1/runs", json={"id": "run-from-key-01", "workflow": "wf", "started_at": "2026-01-01T00:00:00+00:00"},
                   headers={"Authorization": f"Bearer {key}"})
    assert run.status_code == 201 and store.runs["run-from-key-01"]["workspace"] == "ws-a"
    # listing never returns the key or its hash
    listed = api.get("/v1/keys").json()
    assert [k["prefix"] for k in listed] == [key[:12]]
    assert key not in str(listed) and hash_key(key) not in str(listed)


def test_a_member_cannot_manage_keys(login):
    login("ws-a", role="member")
    client = TestClient(app)
    assert client.post("/v1/keys").status_code == 403
    assert client.get("/v1/keys").status_code == 403
    assert client.delete("/v1/keys/k1").status_code == 403


def test_a_revoked_key_stops_working(api):
    key = api.post("/v1/keys").json()["key"]
    key_id = api.get("/v1/keys").json()[0]["id"]
    assert api.delete(f"/v1/keys/{key_id}").status_code == 200
    again = api.post("/v1/runs", json={"id": "run-after-revoke", "workflow": "wf", "started_at": "2026-01-01T00:00:00+00:00"},
                     headers={"Authorization": f"Bearer {key}"})
    assert again.status_code == 401
    assert api.delete(f"/v1/keys/{key_id}").status_code == 404  # already revoked


def test_minting_is_rate_limited(api):
    codes = [api.post("/v1/keys").status_code for _ in range(7)]
    assert codes[:5] == [201] * 5 and codes[5] == 429


# --- importing past runs ---------------------------------------------------------------------

LOG = {
    "workflow": "support_bot",
    "outcome": "fail",
    "steps": [
        {"agent": "router", "input": "My email is jane@acme.com, refund please", "output": "route: billing"},
        {"agent": "billing", "kind": "tool", "tool_name": "lookup", "tool_args": {"id": 7}, "tool_result": {"found": False}},
        {"agent": "billing", "output": "I could not find your account.", "state_after": {"answer": "not found"}},
        {"agent": "reviewer", "output": "approve"},
    ],
}


def test_a_log_becomes_a_run_that_can_be_viewed(api, store):
    resp = api.post("/v1/runs/import", json=LOG)
    assert resp.status_code == 201 and resp.json()["steps"] == 4
    run = api.get(f"/v1/runs/{resp.json()['id']}").json()
    assert run["workflow"] == "support_bot" and run["outcome"] == "fail" and len(run["steps"]) == 4
    # consecutive steps of one agent are one turn; the three agents are three turns
    assert [s["node_run_idx"] for s in run["steps"]] == [1, 2, 2, 3]
    assert run["steps"][2]["state_after"] == {"answer": "not found"} and run["steps"][1]["state_after"] is None
    assert run["forkable"] is False  # not one of our registered workflows: view only


def test_imported_text_is_redacted_like_everything_else(api):
    run_id = api.post("/v1/runs/import", json=LOG).json()["id"]
    first = api.get(f"/v1/runs/{run_id}").json()["steps"][0]
    assert "jane@acme.com" not in str(first) and "REDACTED:email" in str(first)


def test_an_explicit_node_number_groups_steps_and_bad_logs_are_refused(api):
    log = {"workflow": "w", "steps": [{"agent": "a", "node": 5}, {"agent": "b", "node": 5}, {"agent": "a", "node": 9}]}
    run_id = api.post("/v1/runs/import", json=log).json()["id"]
    assert [s["node_run_idx"] for s in api.get(f"/v1/runs/{run_id}").json()["steps"]] == [1, 1, 2]
    assert api.post("/v1/runs/import", json={"workflow": "w", "steps": []}).status_code == 422
    assert api.post("/v1/runs/import", json={"workflow": "w", "steps": [{"kind": "llm"}]}).status_code == 422


def test_a_script_with_a_key_can_import_and_it_lands_in_the_keys_workspace(api, store):
    key = api.post("/v1/keys").json()["key"]
    resp = TestClient(app).post("/v1/import", json=LOG, headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 201
    assert store.runs[resp.json()["id"]]["workspace"] == "ws-a"
    assert TestClient(app).post("/v1/import", json=LOG).status_code == 401


def test_an_import_is_not_visible_to_another_workspace(api, login):
    run_id = api.post("/v1/runs/import", json=LOG).json()["id"]
    login("ws-b")
    assert api.get(f"/v1/runs/{run_id}").status_code == 404


# --- forks and the view-only flag ------------------------------------------------------------

def test_the_workspace_lists_all_its_forks_and_registered_workflows_are_forkable(api, store):
    parent = record(BUGGY_PLAN, "No open tickets.", draft(0), APPROVE)
    run_experiment(parent, n=2)
    forks = api.get("/v1/experiments").json()
    assert len(forks) == 1 and forks[0]["parent_run"] == parent
    assert api.get(f"/v1/runs/{parent}").json()["forkable"] is True


# --- the runs list must not drown in fork attempts -----------------------------------------

def test_the_recorded_filter_keeps_fork_attempts_from_pushing_real_runs_out(api, store):
    real = api.post("/v1/runs/import", json=LOG).json()["id"]
    for i in range(12):  # twelve attempts from forks, all newer than the real run
        store.runs[f"fork-attempt-{i:02d}"] = {"id": f"fork-attempt-{i:02d}", "workspace": "ws-a", "workflow": "wf",
                                               "started_at": f"2099-01-01T00:00:{i:02d}+00:00", "status": "ok", "kind": "fork"}
    newest_50 = [r["id"] for r in api.get("/v1/runs?limit=5").json()]
    assert real not in newest_50  # the problem: the real run is pushed out
    assert [r["id"] for r in api.get("/v1/runs?kind=recorded&limit=5").json()] == [real]
    assert len(api.get("/v1/runs?kind=fork&limit=50").json()) == 12
    assert api.get("/v1/runs?kind=nonsense").status_code == 422


# --- the saved example, copied into a workspace ----------------------------------------------

def seed_example(store):
    """A featured run in the demo workspace, as the seed script leaves it."""
    run_id = record(BUGGY_PLAN, "No open tickets.", draft(0), APPROVE, ws="demo")
    store.runs[run_id].update(outcome="fail", featured=True, oracle_detail={"open_tickets_ok": False})
    return run_id


def test_the_saved_example_is_copied_into_my_workspace_and_can_be_forked(api, store):
    source = seed_example(store)
    resp = api.post("/v1/runs/sample")
    assert resp.status_code == 201 and resp.json()["steps"] == len(
        [k for k in store.steps if k[0] == source])
    copy = api.get(f"/v1/runs/{resp.json()['id']}").json()
    assert copy["id"] != source and copy["outcome"] == "fail" and copy["forkable"] is True
    assert copy["oracle_detail"] == {"open_tickets_ok": False}
    assert store.runs[copy["id"]]["workspace"] == "ws-a"
    assert store.runs[source]["workspace"] == "demo"  # the original is untouched


def test_the_copy_is_a_real_run_that_can_start_a_fork(api, store):
    seed_example(store)
    copy_id = api.post("/v1/runs/sample").json()["id"]
    exp = run_experiment(copy_id, n=2)
    assert api.get(f"/v1/experiments/{exp}").json()["treatment"]["total"] == 2


def test_each_press_makes_a_new_copy_and_another_workspace_never_sees_it(api, store, login):
    seed_example(store)
    first = api.post("/v1/runs/sample").json()["id"]
    second = api.post("/v1/runs/sample").json()["id"]
    assert first != second
    login("ws-b")
    assert api.get(f"/v1/runs/{first}").status_code == 404


def test_without_a_saved_example_the_button_says_so(api):
    assert api.post("/v1/runs/sample").status_code == 404


def test_the_forks_list_says_which_agent_each_fork_changed(api, store):
    parent = record(BUGGY_PLAN, "No open tickets.", draft(0), APPROVE)
    run_experiment(parent, n=2)
    forks = api.get("/v1/experiments").json()
    assert forks[0]["fork_agent"] == "planner"  # the fork was made at the first agent
