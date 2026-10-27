"""Phase 4 route tests against an in-memory fake of app.db (fast, offline).
The real SurrealDB behaviour (idempotent inserts, ordering, isolation) is in test_db_live.py."""

import pytest
from fastapi.testclient import TestClient

from app import db
from app.auth import hash_key
from app.main import app

KEY_A, KEY_B = "at_live_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "at_live_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
RUN = "run0000000000001"
PLANTED = "sk-ant-api03-PLANTEDsecret0123456789_abcDEF"


@pytest.fixture
def store(store):
    store.keys.update({hash_key(KEY_A): "ws-a", hash_key(KEY_B): "ws-b"})
    return store


@pytest.fixture
def client(store):
    return TestClient(app)


def auth(key=KEY_A):
    return {"Authorization": f"Bearer {key}"}


def step(idx, **over):
    return {"idx": idx, "node_run_idx": 1, "agent": "planner", "kind": "llm",
            "origin": "recorded", **over}


def make_run(client, key=KEY_A, run_id=RUN):
    return client.post("/v1/runs", json={"id": run_id, "workflow": "w", "started_at": "2026-01-01T00:00:00Z"},
                       headers=auth(key))


# --- auth ------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer at_live_wrongwrongwrongwrongwrong"}, {"Authorization": "Bearer nope"},
     {"Authorization": "Basic abc"}, {"Authorization": KEY_A}],
)
def test_ingest_without_a_valid_key_is_401(client, headers):
    resp = client.post("/v1/runs", json={"id": RUN, "workflow": "w", "started_at": "t"}, headers=headers)
    assert resp.status_code == 401


def test_every_ingest_route_requires_a_key(client, store):
    make_run(client)
    assert client.post(f"/v1/runs/{RUN}/steps", json={"steps": []}).status_code == 401
    assert client.post(f"/v1/runs/{RUN}/finish", json={"status": "ok"}).status_code == 401


# --- runs and steps --------------------------------------------------------------------------

def test_create_run_is_retry_safe_and_conflicts_across_workspaces(client):
    assert make_run(client).status_code == 201
    assert make_run(client).status_code == 201  # same workspace retry
    assert make_run(client, key=KEY_B).status_code == 409  # id taken by another workspace


def test_workspace_comes_from_the_key_never_the_body(client, store):
    resp = client.post("/v1/runs", headers=auth(),
                       json={"id": RUN, "workflow": "w", "started_at": "t", "workspace": "ws-b"})
    assert resp.status_code == 201
    assert store.runs[RUN]["workspace"] == "ws-a"


def test_steps_for_an_unknown_or_foreign_run_are_404(client):
    assert client.post("/v1/runs/nope000000000000/steps", json={"steps": [step(1)]}, headers=auth()).status_code == 404
    make_run(client)
    assert client.post(f"/v1/runs/{RUN}/steps", json={"steps": [step(1)]}, headers=auth(KEY_B)).status_code == 404


def test_reposting_the_same_batch_does_not_duplicate_steps(client, store):
    make_run(client)
    batch = {"steps": [step(1), step(2)]}
    first = client.post(f"/v1/runs/{RUN}/steps", json=batch, headers=auth()).json()
    again = client.post(f"/v1/runs/{RUN}/steps", json=batch, headers=auth()).json()
    assert first == {"received": 2, "added": 2} and again == {"received": 2, "added": 0}
    assert len(store.steps) == 2


def test_ingest_re_redacts_and_pins_the_step_to_the_url_run(client, store):
    make_run(client)
    leaky = step(1, run="someone-elses-run", input={"messages": [{"content": f"key {PLANTED}"}]},
                 tool_args={"password": "hunter2"})
    client.post(f"/v1/runs/{RUN}/steps", json={"steps": [leaky]}, headers=auth())
    stored = store.steps[(RUN, 1)]
    assert stored["run"] == RUN
    assert PLANTED not in str(stored) and "hunter2" not in str(stored)
    assert {r["type"] for r in stored["redactions"]} == {"api_key", "secret"}


def test_invalid_steps_are_rejected(client):
    make_run(client)
    for bad in (step(0), step(1, kind="nope"), step(1, origin="made-up"), {"idx": 1}):
        resp = client.post(f"/v1/runs/{RUN}/steps", json={"steps": [bad]}, headers=auth())
        assert resp.status_code == 422
    too_many = {"steps": [step(i) for i in range(1, 102)]}
    assert client.post(f"/v1/runs/{RUN}/steps", json=too_many, headers=auth()).status_code == 422


def test_run_ids_must_be_safe_to_use_in_a_record_id(client):
    resp = client.post("/v1/runs", json={"id": "x'; DROP", "workflow": "w", "started_at": "t"}, headers=auth())
    assert resp.status_code == 422


def test_finish_records_outcome_and_detail_and_404s_for_foreign_runs(client, store):
    make_run(client)
    body = {"status": "ok", "outcome": "fail", "oracle_detail": {"footer": {"open_tickets": 0}}}
    assert client.post(f"/v1/runs/{RUN}/finish", json=body, headers=auth()).status_code == 200
    assert store.runs[RUN]["outcome"] == "fail"
    assert client.post(f"/v1/runs/{RUN}/finish", json=body, headers=auth(KEY_B)).status_code == 404


# --- reads -----------------------------------------------------------------------------------

def test_get_run_returns_steps_in_order_and_other_workspaces_get_404(client, store, login):
    make_run(client)
    client.post(f"/v1/runs/{RUN}/steps", json={"steps": [step(2), step(1)]}, headers=auth())
    login("ws-a")
    run = client.get(f"/v1/runs/{RUN}").json()
    assert [s["idx"] for s in run["steps"]] == [1, 2]
    assert [r["id"] for r in client.get("/v1/runs").json()] == [RUN]

    login("ws-b")
    assert client.get(f"/v1/runs/{RUN}").status_code == 404
    assert client.get("/v1/runs").json() == []


def test_reads_require_sign_in(client):
    assert client.get("/v1/runs").status_code == 401
    assert client.get(f"/v1/runs/{RUN}").status_code == 401
