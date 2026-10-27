"""P3: a workflow that is not in our registry is forked end to end through a worker running next to the
customer's code. Offline: the real routes and the real SDK worker, over the in-memory store."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db
from app.experiments import worker as server_worker
from app.main import app
from app.runtime import get_runtime
from agenttrace_sdk import Worker
from agenttrace_sdk.adapters.langgraph import record_langgraph

FLOW = "toy-brief"


def says_five(state):
    return state.get("answer") == "5 open tickets", f"the run said {state.get('answer')!r}"


class ApiSink:
    """The SDK's sink, pointed at the in-process API with an ingest key."""

    def __init__(self, client, key):
        self.c, self.h = client, {"Authorization": f"Bearer {key}"}

    async def start_run(self, run):
        assert self.c.post("/v1/runs", json=run, headers=self.h).status_code == 201

    async def add_steps(self, run_id, steps):
        assert self.c.post(f"/v1/runs/{run_id}/steps", json={"steps": steps}, headers=self.h).status_code == 200

    async def finish_run(self, run_id, status, outcome=None, oracle_detail=None):
        body = {"status": status, "outcome": outcome, "oracle_detail": oracle_detail}
        assert self.c.post(f"/v1/runs/{run_id}/finish", json=body, headers=self.h).status_code == 200


class Transport:
    """What the worker calls, answered by the in-process API."""

    def __init__(self, client, key):
        self.c, self.h = client, {"Authorization": f"Bearer {key}"}

    async def call(self, method, path, payload=None):
        from agenttrace_sdk._http import ApiError
        r = self.c.request(method, path, json=payload, headers=self.h)
        if r.status_code >= 400:
            raise ApiError(r.status_code, r.json().get("detail", ""))
        return r.json()


async def resume(state, rec):
    """The customer's code: run the writer from the restored state. Here the answer follows the filter."""
    answer = "5 open tickets" if state["filter"] == "open" else "0 open tickets"
    state = {**state, "answer": answer}
    await rec.turn("writer", input={"filter": state["filter"]}, output={"answer": answer}, state_after=state,
                   writes=["answer"], tokens_in=10, tokens_out=5)
    return state


@pytest.fixture
def world(store, login):
    login("ws-a", role="admin")
    app.dependency_overrides[get_runtime] = lambda: (None, None)
    with TestClient(app) as client:
        mint = lambda *scopes: client.post("/v1/keys", json={"scopes": list(scopes)}).json()["key"]  # noqa: E731
        yield client, {"ingest": mint("ingest"), "worker": mint("worker"), "read": mint("read")}
    app.dependency_overrides.pop(get_runtime, None)


def record(client, keys, flow=FLOW, writes=True):
    chunks = [{"planner": {"filter": "closed"}}, {"writer": {"answer": "0 open tickets"}}]
    run_id = asyncio.run(record_langgraph(iter(chunks), ApiSink(client, keys["ingest"]), flow, input={"request": "brief"}, oracle=says_five))
    return run_id


def start(client, run_id, n=3, edit=None):
    return client.post("/v1/experiments", json={"run_id": run_id, "fork_node_run_idx": 1, "edit": edit or {"filter": "open"}, "n": n})


def make_worker(client, keys, oracle=says_five, name="w1", fn=resume):
    w = Worker(name=name, client=Transport(client, keys["worker"]))
    w.register(FLOW, fn, oracle=oracle, safe_to_rerun=True)
    return w


def drain(w):
    done = 0
    while asyncio.run(w.run_once()):
        done += 1
    return done


# --- the Done-when line ----------------------------------------------------------------------

def test_a_workflow_we_do_not_run_is_forked_end_to_end_through_a_worker_with_k_over_n_and_a_p_value(world, store):
    client, keys = world
    run_id = record(client, keys)
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["outcome"] == "fail" and run["forkable"] is True and run["fork_mode"] == "worker"

    resp = start(client, run_id, n=3)
    assert resp.status_code == 202
    exp = client.get(f"/v1/experiments/{resp.json()['id']}").json()
    assert exp["mode"] == "worker" and exp["status"] == "queued" and exp["control"]["total"] == 0  # waiting for a worker

    assert drain(make_worker(client, keys)) == 6  # 3 without the change, 3 with it
    exp = client.get(f"/v1/experiments/{exp['id']}").json()
    assert exp["status"] == "done"
    assert (exp["control"], exp["treatment"]) == ({"pass": 0, "total": 3}, {"pass": 3, "total": 3})
    assert exp["stats"]["fisher_p"] == pytest.approx(0.1) and "directional" in exp["stats"]["label"]
    assert exp["tokens_used"] == 6 * 15 and all(t["status"] == "done" and t["run_id"] for t in exp["tiles"])

    # Each attempt is a fork run: recorded steps replayed exactly, the change as one edited step, the rest live.
    by_arm = {t["arm"]: t["run_id"] for t in exp["tiles"]}
    treated = client.get(f"/v1/runs/{by_arm['treatment']}").json()
    control = client.get(f"/v1/runs/{by_arm['control']}").json()
    assert [(s["idx"], s["node_run_idx"], s["agent"], s["origin"]) for s in treated["steps"]] == [(1, 1, "planner", "edited"), (2, 2, "writer", "live")]
    assert treated["steps"][0]["output"] == {"edited_updates": {"filter": "open"}}
    assert [(s["idx"], s["agent"], s["origin"]) for s in control["steps"]] == [(1, "planner", "replayed"), (2, "writer", "live")]
    assert (treated["outcome"], control["outcome"], treated["kind"]) == ("pass", "fail", "fork")
    assert treated["oracle_detail"]["verdict"]["kind"] == "code"
    # fork attempts do not clutter the list of recorded runs
    assert [r["id"] for r in client.get("/v1/runs?kind=recorded").json()] == [run_id]
    # and the experiment shows on the original run's line
    assert [e["id"] for e in client.get(f"/v1/runs/{run_id}/experiments").json()] == [exp["id"]]


def test_a_run_with_no_recorded_state_or_no_declared_writes_is_view_only(world):
    client, keys = world
    # a trace sent over OpenTelemetry carries neither
    ids = []
    for state in (None, {"x": 1}):
        run_id = f"run0000000000{len(ids)}"
        ids.append(run_id)
        sink = ApiSink(client, keys["ingest"])
        asyncio.run(sink.start_run({"id": run_id, "workflow": FLOW, "started_at": "2026-01-01T00:00:00+00:00"}))
        step = {"idx": 1, "node_run_idx": 1, "agent": "a", "kind": "llm", "origin": "recorded", "state_after": state}
        asyncio.run(sink.add_steps(run_id, [step]))
    assert [client.get(f"/v1/runs/{r}").json()["forkable"] for r in ids] == [False, False]


def test_an_edit_that_changes_a_key_the_agent_never_wrote_is_refused(world):
    client, keys = world
    run_id = record(client, keys)
    resp = start(client, run_id, edit={"answer": "5"})  # the planner wrote `filter`, not `answer`
    assert resp.status_code == 422 and "not writes" in resp.json()["detail"]


# --- keys and workspaces ---------------------------------------------------------------------

def test_each_key_can_do_only_what_its_scopes_say(world):
    client, keys = world
    run = {"id": "run00000000099", "workflow": FLOW, "started_at": "2026-01-01T00:00:00+00:00"}
    h = lambda k: {"Authorization": f"Bearer {keys[k]}"}  # noqa: E731
    claim = {"workflows": [FLOW]}
    assert client.post("/v1/runs", json=run, headers=h("worker")).status_code == 403  # a worker cannot ingest
    assert client.post("/v1/worker/claim", json=claim, headers=h("ingest")).status_code == 403  # nor an ingest key claim
    assert client.post("/v1/worker/claim", json=claim, headers=h("read")).status_code == 403
    assert client.post("/v1/worker/claim", json=claim, headers=h("worker")).json() == {"job": None}
    assert client.post("/v1/worker/claim", json=claim).status_code == 401


def test_another_workspaces_worker_gets_no_job_and_cannot_report(world, login):
    client, keys = world
    run_id = record(client, keys)
    exp_id = start(client, run_id).json()["id"]
    job = asyncio.run(Transport(client, keys["worker"]).call("POST", "/v1/worker/claim", {"workflows": [FLOW]}))["job"]
    login("ws-b", role="admin")
    other = client.post("/v1/keys", json={"scopes": ["worker"]}).json()["key"]
    assert client.post("/v1/worker/claim", json={"workflows": [FLOW]}, headers={"Authorization": f"Bearer {other}"}).json() == {"job": None}
    result = {"experiment": exp_id, "claim": job["claim"], "arm": job["arm"], "i": job["i"], "outcome": "pass"}
    assert client.post("/v1/worker/results", json=result, headers={"Authorization": f"Bearer {other}"}).status_code == 404


# --- jobs ------------------------------------------------------------------------------------

def test_two_workers_never_take_the_same_job_and_a_stale_claim_loses(world, store):
    client, keys = world
    exp_id = start(client, record(client, keys), n=2).json()["id"]
    t = Transport(client, keys["worker"])
    taken = [asyncio.run(t.call("POST", "/v1/worker/claim", {"workflows": [FLOW], "worker": f"w{i}"}))["job"] for i in range(4)]
    assert sorted((j["arm"], j["i"]) for j in taken) == [("control", 1), ("control", 2), ("treatment", 1), ("treatment", 2)]
    assert asyncio.run(t.call("POST", "/v1/worker/claim", {"workflows": [FLOW]}))["job"] is None  # nothing left to take
    # the compare-and-set that makes that safe: a write from a stale read is refused
    assert asyncio.run(db.update_experiment_if_rev("ws-a", exp_id, 0, {"rev": 99})) is False
    # the state a job carries: the change applied for the treatment run only
    assert {j["arm"]: j["state"]["filter"] for j in taken} == {"control": "closed", "treatment": "open"}


def test_a_result_is_recorded_once_and_only_for_the_claim_that_holds_the_job(world):
    client, keys = world
    exp_id = start(client, record(client, keys), n=1).json()["id"]
    t = Transport(client, keys["worker"])
    job = asyncio.run(t.call("POST", "/v1/worker/claim", {"workflows": [FLOW]}))["job"]
    body = {"experiment": exp_id, "claim": job["claim"], "arm": job["arm"], "i": 1, "outcome": "pass"}
    forged = client.post("/v1/worker/results", json={**body, "claim": "0" * 32}, headers={"Authorization": f"Bearer {keys['worker']}"})
    assert forged.status_code == 409
    assert asyncio.run(t.call("POST", "/v1/worker/results", body))["recorded"] is True
    assert asyncio.run(t.call("POST", "/v1/worker/results", body)) == {"recorded": False, "detail": "already recorded"}
    exp = client.get(f"/v1/experiments/{exp_id}").json()
    assert exp[job["arm"]]["total"] == 1  # counted once


def test_a_job_whose_worker_went_quiet_goes_back_in_the_queue_and_is_an_error_after_three_tries(world, store):
    client, keys = world
    exp_id = start(client, record(client, keys), n=1).json()["id"]
    t = Transport(client, keys["worker"])
    long_ago = (datetime.now(UTC) - timedelta(seconds=server_worker.LEASE_SECONDS + 5)).isoformat()
    for attempt in (1, 2, 3):
        job = asyncio.run(t.call("POST", "/v1/worker/claim", {"workflows": [FLOW]}))["job"]
        assert job is not None and job["arm"] == "control"
        for tile in store.experiments[exp_id]["tiles"]:
            if tile["status"] == "running":
                tile["claimed_at"] = long_ago  # the worker never reported
    # the third lease also ran out: that job is spent, and counts as a run that did not pass
    asyncio.run(t.call("POST", "/v1/worker/claim", {"workflows": [FLOW]}))
    control = next(x for x in store.experiments[exp_id]["tiles"] if x["arm"] == "control")
    assert control["status"] == "done" and control["outcome"] == "error"
    assert store.experiments[exp_id]["control"] == {"pass": 0, "total": 1}


def test_the_token_ceiling_holds_for_what_workers_report(world, store):
    client, keys = world
    exp_id = start(client, record(client, keys), n=3).json()["id"]
    store.experiments[exp_id]["token_ceiling"] = 30  # two jobs (15 tokens each) reach it
    drain(make_worker(client, keys))
    exp = client.get(f"/v1/experiments/{exp_id}").json()
    assert exp["status"] == "capped"
    assert sorted(t["status"] for t in exp["tiles"]).count("skipped") == 4 and exp["tokens_used"] == 30


# --- the worker ------------------------------------------------------------------------------

def test_a_resume_function_that_crashes_is_an_error_run_and_the_worker_carries_on(world):
    client, keys = world
    exp_id = start(client, record(client, keys), n=1).json()["id"]

    async def broken(state, rec):
        raise RuntimeError("tool is down")
    assert drain(make_worker(client, keys, fn=broken)) == 2
    exp = client.get(f"/v1/experiments/{exp_id}").json()
    assert exp["status"] == "done" and (exp["control"], exp["treatment"]) == ({"pass": 0, "total": 1}, {"pass": 0, "total": 1})
    failed = client.get(f"/v1/runs/{exp['tiles'][0]['run_id']}").json()
    assert failed["outcome"] == "error" and "RuntimeError" in failed["oracle_detail"]["verdict"]["reason"]
    assert "tool is down" not in str(failed)  # the message could hold data: only the type is kept


def test_a_worker_only_takes_jobs_for_workflows_it_registered_and_must_say_a_rerun_is_safe(world):
    client, keys = world
    start(client, record(client, keys))
    other = Worker(client=Transport(client, keys["worker"]))
    other.register("some-other-flow", resume, oracle=says_five, safe_to_rerun=True)
    assert asyncio.run(other.run_once()) is False
    with pytest.raises(ValueError, match="safe_to_rerun"):
        Worker(client=Transport(client, keys["worker"])).register(FLOW, resume, oracle=says_five, safe_to_rerun=False)


def test_the_app_can_tell_whether_a_worker_is_connected(world, store):
    client, keys = world
    exp_id = start(client, record(client, keys), n=1).json()["id"]
    assert client.get(f"/v1/experiments/{exp_id}").json()["workers_online"] == 0  # nobody has asked for a job
    asyncio.run(Transport(client, keys["worker"]).call("POST", "/v1/worker/claim", {"workflows": ["some-other-flow"]}))  # asking is enough
    assert client.get(f"/v1/experiments/{exp_id}").json()["workers_online"] == 1
    read = Transport(client, keys["read"])
    assert asyncio.run(read.call("GET", f"/v1/agent/experiments/{exp_id}"))["workers_online"] == 1
    for k in store.api_keys:  # a worker that has gone quiet for two minutes is not connected
        if "worker" in k["scopes"]:
            k["last_seen_at"] = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    assert client.get(f"/v1/experiments/{exp_id}").json()["workers_online"] == 0

