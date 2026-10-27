"""Phase 10: the public, no-sign-in demo routes. They must serve the demo workspace and nothing
else, expose no writes, and be cached."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.experiments import runner
from app.main import app
from app.routes import public
from test_experiments import FakeLLM, FixtureTools
from test_fork import FIXED_PLAN, record
from test_renewal_brief import APPROVE, BUGGY_PLAN, draft

DEMO = "demo"


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    monkeypatch.setattr(public, "CACHE_TTL_S", 0.0)
    public._cache.clear()


@pytest.fixture
def client(store):
    return TestClient(app)  # note: no login override. These routes need no sign-in.


def make_demo(store, ws=DEMO):
    """A featured failing run, a stored RCA report and two featured experiments in `ws`."""
    run_id = record(BUGGY_PLAN, "No open tickets.", draft(0), APPROVE, ws=ws)
    store.runs[run_id].update(outcome="fail", featured=True)

    async def experiments():
        ids = []
        for role, edit in (("hero", FIXED_PLAN), ("decoy", {"plan": {**FIXED_PLAN["plan"], "note": "x"}})):
            exp_id = await runner.create_experiment(
                ws, run_id, 1, edit, 2, client=FakeLLM(), tools=FixtureTools(), created_by="seed"
            )
            await runner._TASKS[exp_id]
            store.experiments[exp_id].update(featured=True, demo_role=role)
            ids.append(exp_id)
        return ids

    return run_id, asyncio.run(experiments())


def test_the_demo_is_served_without_signing_in(client, store):
    run_id, _ = make_demo(store)
    resp = client.get("/v1/public/demo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"]["id"] == run_id and len(body["run"]["steps"]) == 6
    assert body["rca"] is None  # nothing stored yet
    assert resp.headers["cache-control"] == "public, max-age=60"


def test_experiments_come_back_decoy_first_then_hero_with_their_results(client, store):
    make_demo(store)
    experiments = client.get("/v1/public/demo").json()["experiments"]
    assert [e["role"] for e in experiments] == ["decoy", "hero"]
    assert all(e["stats"]["label"].startswith("directional") for e in experiments)
    hero = experiments[1]
    assert hero["control"] == {"pass": 0, "total": 2} and hero["treatment"] == {"pass": 2, "total": 2}


def test_a_stored_root_cause_report_is_included(client, store):
    run_id, _ = make_demo(store)
    asyncio.run(store.create_rca_report(DEMO, "r1", {
        "run": run_id, "lineage": [1, 2, 3], "created_at": "2026-01-01T00:00:00Z", "model": "m",
        "tokens_in": 1, "tokens_out": 1, "candidates": [
            {"node_run_idx": 1, "step_idx": 1, "confidence": 0.8, "hypothesis": "h", "evidence_quotes": []}
        ],
    }))
    rca = client.get("/v1/public/demo").json()["rca"]
    assert rca["candidates"][0]["proposed_edit"] is None and rca["lineage"] == [1, 2, 3]


def test_only_the_demo_workspace_is_ever_served(client, store):
    mine, _ = make_demo(store, ws="ws-a")  # featured, but in someone else's workspace
    assert client.get("/v1/public/demo").status_code == 404  # demo workspace has nothing featured
    assert client.get(f"/v1/public/demo/runs/{mine}").status_code == 404  # and cannot read their run by id

    demo_run, _ = make_demo(store)
    body = client.get("/v1/public/demo").json()
    assert body["run"]["id"] == demo_run and body["run"]["id"] != mine


def test_the_workspace_cannot_be_chosen_by_the_caller(client, store):
    mine, _ = make_demo(store, ws="ws-a")
    demo_run, _ = make_demo(store)
    for url in (f"/v1/public/demo?workspace=ws-a", f"/v1/public/demo/runs/{mine}?workspace=ws-a"):
        resp = client.get(url, headers={"X-Workspace": "ws-a"})
        assert mine not in resp.text
    assert client.get(f"/v1/public/demo/runs/{demo_run}").status_code == 200


def test_unseeded_demo_and_unknown_runs_are_404(client, store):
    assert client.get("/v1/public/demo").status_code == 404
    assert client.get("/v1/public/demo/runs/nope0000000000000").status_code == 404


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize("path", ["/v1/public/demo", "/v1/public/demo/runs/abc"])
def test_there_are_no_write_endpoints(client, method, path):
    assert getattr(client, method)(path).status_code == 405


def test_responses_are_cached_in_memory(client, store, monkeypatch):
    monkeypatch.setattr(public, "CACHE_TTL_S", 60.0)
    run_id, _ = make_demo(store)
    first = client.get("/v1/public/demo").json()
    store.runs[run_id]["status"] = "changed-after-cache"
    assert client.get("/v1/public/demo").json() == first  # served from the cache
    public._cache.clear()
    assert client.get("/v1/public/demo").json()["run"]["status"] == "changed-after-cache"


def test_the_private_routes_are_still_private(client):
    assert client.get("/v1/runs").status_code == 401
    assert client.post("/v1/experiments", json={}).status_code == 401
