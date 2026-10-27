"""Phase 6: the experiment runner and its routes, offline. A deterministic fake LLM answers from
what it is shown (the writer reports 0 tickets if it was only shown solved ones), so control
fails and treatment passes without depending on call order under concurrency."""

import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.experiments import runner
from app.experiments.stats import fisher_exact_two_sided
from app.auth import get_principal
from app.main import app
from app.runtime import get_runtime
from app.workflows.renewal_brief.tools import FixtureTools
from test_fork import FIXED_PLAN, WS, record
from test_renewal_brief import APPROVE, BUGGY_PLAN, draft


class FakeLLM:
    def __init__(self) -> None:
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        system, user = kw["system"], kw["messages"][0]["content"]
        if system.startswith("You are the research agent"):
            text = "summary"
        elif system.startswith("You are the writing agent"):
            text = draft(0 if '"statuses_requested": ["solved"]' in user else 4)
        elif system.startswith("You are the reviewing agent"):
            text = APPROVE
        else:
            raise AssertionError(f"unexpected prompt: {system[:40]}")
        block = SimpleNamespace(type="text", text=text, model_dump=lambda mode="python": {"type": "text", "text": text})
        return SimpleNamespace(content=[block], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))


class BrokenLLM:
    messages = SimpleNamespace(create=None)

    def __init__(self) -> None:
        async def boom(**kw):
            raise RuntimeError("model unavailable")

        self.messages = SimpleNamespace(create=boom)


@pytest.fixture
def parent(store):
    return record(BUGGY_PLAN, "No open tickets.", draft(0), APPROVE)


def run_experiment(parent_id, n=3, client=None, edit=FIXED_PLAN):
    async def go():
        exp_id = await runner.create_experiment(
            WS, parent_id, 1, edit, n, client=client or FakeLLM(), tools=FixtureTools(), created_by="t"
        )
        await runner._TASKS[exp_id]
        return exp_id

    return asyncio.run(go())


# --- the runner ------------------------------------------------------------------------------

def test_one_experiment_runs_both_arms_and_stores_counts_stats_and_edges(store, parent):
    exp_id = run_experiment(parent, n=3)
    doc = runner.view(store.experiments[exp_id])

    assert doc["status"] == "done"
    assert doc["control"] == {"pass": 0, "total": 3} and doc["treatment"] == {"pass": 3, "total": 3}
    assert doc["stats"]["fisher_p"] == pytest.approx(fisher_exact_two_sided(3, 0, 0, 3))
    assert doc["stats"]["label"] == "directional evidence, N=3"
    assert doc["stats"]["wilson"]["control"][0] == 0
    assert len(doc["tiles"]) == 6 and all(t["status"] == "done" and t["run_id"] for t in doc["tiles"])
    assert {(t["arm"], t["outcome"]) for t in doc["tiles"]} == {("control", "fail"), ("treatment", "pass")}
    assert doc["tokens_used"] > 0

    # every run is stored, linked to the parent (forked_from) and to the experiment (tested)
    assert sorted(r for _, r in store.tested) == sorted(t["run_id"] for t in doc["tiles"])
    forks = [f for f in store.forks if f["parent"] == parent]
    assert len(forks) == 6 and {f["experiment"] for f in forks} == {exp_id}
    assert sorted(f["arm"] for f in forks) == ["control"] * 3 + ["treatment"] * 3


def test_the_control_arm_never_gets_the_edit(store, parent):
    exp_id = run_experiment(parent, n=2)
    for tile in store.experiments[exp_id]["tiles"]:
        steps = asyncio.run(store.get_run_with_steps(WS, tile["run_id"]))["steps"]
        assert steps[0]["origin"] == ("edited" if tile["arm"] == "treatment" else "replayed")


def test_edit_is_stored_redacted(store, parent):
    exp_id = run_experiment(parent, n=1, edit={"plan": {**FIXED_PLAN["plan"], "note": "mail a@b.io"}})
    assert "a@b.io" not in str(store.experiments[exp_id]["edit_patch"])


@pytest.mark.parametrize("n", [0, 9, -1])
def test_n_outside_one_to_max_n_is_refused_before_anything_is_created(store, parent, n):
    with pytest.raises(ValueError, match="between 1 and 8"):
        run_experiment(parent, n=n)
    assert store.experiments == {}


def test_a_lower_max_n_from_the_environment_is_enforced(store, parent, monkeypatch):
    monkeypatch.setenv("MAX_N", "2")
    with pytest.raises(ValueError, match="between 1 and 2"):
        run_experiment(parent, n=3)


def test_the_token_ceiling_stops_new_runs_and_marks_the_experiment_capped(store, parent, monkeypatch):
    monkeypatch.setenv("MAX_TOKENS_PER_EXPERIMENT", "1")
    exp_id = run_experiment(parent, n=4)
    doc = runner.view(store.experiments[exp_id])

    statuses = [t["status"] for t in doc["tiles"]]
    assert doc["status"] == "capped" and "skipped" in statuses and statuses.count("done") >= 1
    # only completed runs are counted; skipped ones are not failures
    assert doc["control"]["total"] + doc["treatment"]["total"] == statuses.count("done")


def test_runs_that_error_count_as_failures_and_do_not_stop_the_experiment(store, parent):
    exp_id = run_experiment(parent, n=2, client=BrokenLLM())
    doc = runner.view(store.experiments[exp_id])
    assert doc["status"] == "done"
    assert doc["control"] == {"pass": 0, "total": 2} and doc["treatment"] == {"pass": 0, "total": 2}
    assert {t["outcome"] for t in doc["tiles"]} == {"error"}


# --- the routes ------------------------------------------------------------------------------

@pytest.fixture
def api(store, login):
    login("ws-a")
    app.dependency_overrides[get_runtime] = lambda: (FakeLLM(), FixtureTools())
    with TestClient(app) as client:  # one event loop for the whole test, so background tasks live
        yield client
    app.dependency_overrides.pop(get_runtime, None)


def wait_done(api, exp_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = api.get(f"/v1/experiments/{exp_id}").json()
        if body["status"] in ("done", "capped", "error"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"experiment still {body['status']}")


def post(api, parent_id, **over):
    body = {"run_id": parent_id, "fork_node_run_idx": 1, "edit": FIXED_PLAN, "n": 3, **over}
    return api.post("/v1/experiments", json=body)


def test_one_post_returns_immediately_and_polling_shows_the_result(api, parent):
    resp = post(api, parent)
    assert resp.status_code == 202
    body = wait_done(api, resp.json()["id"])
    assert body["control"] == {"pass": 0, "total": 3} and body["treatment"] == {"pass": 3, "total": 3}
    assert body["stats"]["label"].startswith("directional")
    assert body["parent_run"] == parent and body["fork_node_run_idx"] == 1


def test_a_bad_request_is_refused_with_a_clear_status(api, store, parent):
    assert post(api, "nope0000000000000").status_code == 404
    assert post(api, parent, fork_node_run_idx=9).status_code == 422
    assert post(api, parent, edit={"findings": {}}).status_code == 422  # not a write of node run 1
    assert post(api, parent, edit={}).status_code == 422
    assert post(api, parent, n=9).status_code == 422
    assert post(api, parent, n=0).status_code == 422
    store.steps[(parent, 1)]["model"] = "claude-haiku-4-5"
    assert post(api, parent).status_code == 409  # recorded with other model settings
    assert store.experiments == {}


def test_experiments_are_scoped_to_the_callers_workspace(api, parent, login):
    exp_id = post(api, parent).json()["id"]
    wait_done(api, exp_id)
    login("ws-b")
    assert api.get(f"/v1/experiments/{exp_id}").status_code == 404
    assert post(api, parent).status_code == 404  # ws-b cannot fork ws-a's run


def test_experiment_routes_require_sign_in(api, parent):
    app.dependency_overrides.pop(get_principal)  # log out
    assert post(api, parent).status_code == 401
    assert api.get("/v1/experiments/abc").status_code == 401


# --- the forks of a run (the branches of its graph) -----------------------------------------

def test_the_forks_of_a_run_are_listed_for_its_own_workspace_only(api, parent):
    first = run_experiment(parent, n=2)
    second = run_experiment(parent, n=2)
    listed = api.get(f"/v1/runs/{parent}/experiments")
    assert listed.status_code == 200
    ids = [e["id"] for e in listed.json()]
    assert ids == [first, second] or set(ids) == {first, second}
    assert listed.json()[0]["control"]["total"] == 2 and "tiles" in listed.json()[0]


def test_a_run_with_no_forks_lists_none_and_an_unknown_run_is_404(api, parent):
    assert api.get(f"/v1/runs/{parent}/experiments").json() == []
    assert api.get("/v1/runs/not-a-run/experiments").status_code == 404


def test_another_workspace_cannot_list_the_forks(api, parent, login):
    run_experiment(parent, n=2)
    login("ws-b")
    assert api.get(f"/v1/runs/{parent}/experiments").status_code == 404


def test_forks_of_forks_are_listed_with_the_run_they_branch_from(api, parent):
    first = run_experiment(parent, n=2)
    made = api.get(f"/v1/experiments/{first}").json()
    attempt = next(t["run_id"] for t in made["tiles"] if t["arm"] == "treatment" and t["run_id"])
    second = run_experiment(attempt, n=2)  # a fork made from one of the first fork's own runs
    listed = {e["id"]: e["parent_run"] for e in api.get(f"/v1/runs/{parent}/experiments").json()}
    assert listed == {first: parent, second: attempt}
