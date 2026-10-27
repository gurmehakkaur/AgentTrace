"""Phase 1 and 4 against the REAL SurrealDB. Skipped unless RUN_LIVE=1:

    RUN_LIVE=1 api/.venv/bin/pytest api/tests/test_db_live.py

Each test uses a throwaway `test-<random>` workspace and purges it afterwards."""

import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app import db
from app.auth import KEY_PREFIX, Principal, get_principal, hash_key
from app.main import app

pytestmark = pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 to hit SurrealDB")


def run(coro):
    return asyncio.run(coro)


def new_id() -> str:
    return uuid.uuid4().hex


def step(run_id, idx, **over):
    return {"run": run_id, "idx": idx, "node_run_idx": idx, "agent": f"a{idx}", "kind": "llm",
            "origin": "recorded", "tokens_in": 10, "tokens_out": 5, **over}


@pytest.fixture(scope="module", autouse=True)
def schema():
    run(db.apply_schema())


@pytest.fixture
def ws():
    name = f"test-{uuid.uuid4().hex[:8]}"
    yield name
    run(db.purge_workspace(name))


def test_steps_come_back_in_order_even_when_inserted_out_of_order(ws):
    rid = new_id()
    run(db.create_run(ws, rid, "w", "2026-01-01T00:00:00+00:00"))
    run(db.add_steps(ws, rid, [step(rid, 3), step(rid, 1)]))
    run(db.add_steps(ws, rid, [step(rid, 2)]))
    result = run(db.get_run_with_steps(ws, rid))
    assert [s["idx"] for s in result["steps"]] == [1, 2, 3]
    assert result["id"] == rid and result["workspace"] == ws


def test_reposting_a_batch_adds_no_duplicate_steps_or_edges(ws):
    rid = new_id()
    run(db.create_run(ws, rid, "w", "t"))
    batch = [step(rid, 1), step(rid, 2)]
    assert run(db.add_steps(ws, rid, batch)) == 2
    assert run(db.add_steps(ws, rid, batch)) == 0
    assert len(run(db.get_run_with_steps(ws, rid))["steps"]) == 2

    async def edge_counts():
        async with db.connect() as c:
            has = await c.query("SELECT count() AS n FROM has_step WHERE in = type::record('run', $r) GROUP ALL", {"r": rid})
            nxt = await c.query("SELECT count() AS n FROM next WHERE in.run = $r GROUP ALL", {"r": rid})
        return has[0]["n"], nxt[0]["n"]

    assert run(edge_counts()) == (2, 1)  # two has_step edges, one next edge (step1 -> step2)


def test_a_run_is_invisible_to_other_workspaces(ws):
    rid = new_id()
    run(db.create_run(ws, rid, "w", "t"))
    assert run(db.run_exists(ws, rid)) and not run(db.run_exists("test-other", rid))
    assert run(db.get_run_with_steps("test-other", rid)) is None
    assert run(db.list_runs("test-other")) == []
    assert run(db.finish_run("test-other", rid, "ok", "pass", None)) is False
    with pytest.raises(db.RunConflict):
        run(db.create_run("test-other", rid, "w", "t"))


def test_finish_run_sums_tokens_and_stores_the_oracle_result(ws):
    rid = new_id()
    run(db.create_run(ws, rid, "w", "t"))
    run(db.add_steps(ws, rid, [step(rid, 1), step(rid, 2)]))
    assert run(db.finish_run(ws, rid, "ok", "fail", {"footer": {"open_tickets": 0}}))
    got = run(db.get_run_with_steps(ws, rid))
    assert (got["status"], got["outcome"], got["tokens_in"], got["tokens_out"]) == ("ok", "fail", 20, 10)
    assert got["oracle_detail"] == {"footer": {"open_tickets": 0}}


def test_list_runs_is_newest_first(ws):
    old, new = new_id(), new_id()
    run(db.create_run(ws, old, "w", "2026-01-01T00:00:00+00:00"))
    run(db.create_run(ws, new, "w", "2026-02-01T00:00:00+00:00"))
    assert [r["id"] for r in run(db.list_runs(ws))] == [new, old]


def test_list_forks_is_empty_for_a_fresh_run_then_shows_the_fork(ws):
    parent, fork = new_id(), new_id()
    run(db.create_run(ws, parent, "w", "t"))
    run(db.create_run(ws, fork, "w", "t"))
    assert run(db.list_forks(ws, parent)) == []
    run(db.create_fork_edge(ws, fork, parent, at_idx=2, arm="treatment", experiment=None))
    assert run(db.list_forks(ws, parent)) == [
        {"fork_run": fork, "at_idx": 2, "arm": "treatment", "experiment": None}
    ]
    assert run(db.list_forks("test-other", parent)) == []


def test_end_to_end_ingest_over_http_with_a_real_key(ws, request):
    """SDK-shaped requests -> routes -> SurrealDB -> GET, including a wrong key and a re-post."""
    key = KEY_PREFIX + uuid.uuid4().hex
    run(db.upsert_workspace(ws, "live test"))
    run(db.create_api_key(ws, key[:12], hash_key(key), "test"))
    app.dependency_overrides[get_principal] = lambda: Principal("user_1", ws, "member")
    request.addfinalizer(lambda: app.dependency_overrides.pop(get_principal, None))
    client, auth, rid = TestClient(app), {"Authorization": f"Bearer {key}"}, new_id()

    assert client.post("/v1/runs", headers={"Authorization": "Bearer at_live_wrong"},
                       json={"id": rid, "workflow": "w", "started_at": "t"}).status_code == 401
    assert client.post("/v1/runs", headers=auth, json={"id": rid, "workflow": "w", "started_at": "t"}).status_code == 201
    batch = {"steps": [{"idx": i, "node_run_idx": 1, "agent": "p", "kind": "llm", "origin": "recorded"} for i in (1, 2)]}
    assert client.post(f"/v1/runs/{rid}/steps", headers=auth, json=batch).json()["added"] == 2
    assert client.post(f"/v1/runs/{rid}/steps", headers=auth, json=batch).json()["added"] == 0
    client.post(f"/v1/runs/{rid}/finish", headers=auth, json={"status": "ok", "outcome": "fail"})

    got = client.get(f"/v1/runs/{rid}").json()
    assert [s["idx"] for s in got["steps"]] == [1, 2] and got["outcome"] == "fail"


def test_delete_run_cascade_removes_the_run_its_forks_and_everything_derived(ws):
    other_ws = f"{ws}-other"
    parent, fork, nested, keep, foreign = (new_id() for _ in range(5))
    for rid, w in ((parent, ws), (fork, ws), (nested, ws), (keep, ws), (foreign, other_ws)):
        run(db.create_run(w, rid, "w", "2026-01-01T00:00:00+00:00"))
        run(db.add_steps(w, rid, [step(rid, 1), step(rid, 2)]))
    run(db.create_fork_edge(ws, fork, parent, 1, "treatment"))
    run(db.create_fork_edge(ws, nested, fork, 1, "control"))  # a fork of a fork
    exp_id = new_id()
    run(db.create_experiment(ws, exp_id, {"parent_run": parent, "remembered": True, "memory_scope": "ws/x/workflow/w/run/p",
                                          "finished_at": "2026-01-01T00:00:00+00:00"}))
    run(db.create_tested_edge(exp_id, fork))
    run(db.create_rca_report(ws, new_id(), {"run": parent, "created_at": "2026-01-01T00:00:00+00:00"}))

    assert run(db.delete_run_cascade(other_ws, parent)) is None  # another workspace cannot reach it
    assert run(db.get_run_with_steps(ws, parent)) is not None

    result = run(db.delete_run_cascade(ws, parent))
    assert (result["runs"], result["steps"], result["experiments"], result["rca_reports"]) == (3, 6, 1, 1)
    assert result["memory_scopes"] == ["ws/x/workflow/w/run/p"]

    for gone in (parent, fork, nested):
        assert run(db.get_run_with_steps(ws, gone)) is None
    assert len(run(db.get_run_with_steps(ws, keep))["steps"]) == 2  # unrelated run untouched
    assert len(run(db.get_run_with_steps(other_ws, foreign))["steps"]) == 2

    async def leftovers():
        async with db.connect() as c:
            q = lambda sql, **v: c.query(sql, v)  # noqa: E731
            return [
                await q("SELECT id FROM experiment WHERE workspace = $ws", ws=ws),
                await q("SELECT id FROM rca_report WHERE workspace = $ws", ws=ws),
                await q("SELECT id FROM tested WHERE in = type::record('experiment', $e)", e=exp_id),
                await q("SELECT id FROM forked_from WHERE in.workspace = $ws", ws=ws),
                await q("SELECT id FROM step WHERE run IN $ids", ids=[parent, fork, nested]),
            ]

    assert [len(x) for x in run(leftovers())] == [0, 0, 0, 0, 0]
    run(db.purge_workspace(other_ws))


def test_audit_records_and_the_daily_experiment_count_work_against_the_real_database(ws):
    run(db.create_audit(ws, {"actor": "u1", "action": "run.delete", "target": "r1", "detail": {}, "at": "2026-01-02T00:00:00+00:00"}))
    run(db.create_audit(ws, {"actor": "u1", "action": "experiment.launch", "target": "e1", "detail": {}, "at": "2026-01-03T00:00:00+00:00"}))
    assert [a["action"] for a in run(db.list_audit(ws))] == ["experiment.launch", "run.delete"]
    assert run(db.list_audit("test-someone-else")) == []

    user = f"user-{uuid.uuid4().hex[:6]}"
    for i, when in enumerate(["2026-01-01T10:00:00+00:00", "2026-01-02T01:00:00+00:00", "2026-01-02T23:00:00+00:00"]):
        run(db.create_experiment(ws, new_id(), {"created_by": user, "created_at": when, "parent_run": "x"}))
    assert run(db.count_experiments_since(user, "2026-01-02T00:00:00+00:00")) == 2
    assert run(db.count_experiments_since(user, "2026-01-03T00:00:00+00:00")) == 0


def test_a_key_made_before_scopes_can_only_ingest_and_a_new_one_keeps_its_scopes(ws):
    run(db.create_api_key(ws, "at_live_old1", hash_key("old-" + ws), "user_1"))  # made without scopes
    run(db.create_api_key(ws, "at_live_new1", hash_key("new-" + ws), "user_1", ("read", "spend")))
    old, new = run(db.key_for_hash(hash_key("old-" + ws))), run(db.key_for_hash(hash_key("new-" + ws)))
    assert old["workspace"] == ws and old["scopes"] == ["ingest"]
    assert new["scopes"] == ["read", "spend"]
    assert sorted(k["scopes"] for k in run(db.list_api_keys(ws))) == [["ingest"], ["read", "spend"]]


def test_two_writers_cannot_both_take_the_same_experiment_revision(ws):
    eid = new_id()
    run(db.create_experiment(ws, eid, {"status": "queued", "rev": 0, "tiles": [{"arm": "control", "i": 1, "status": "queued"}]}))
    won = run(db.update_experiment_if_rev(ws, eid, 0, {"status": "running", "rev": 1}))
    lost = run(db.update_experiment_if_rev(ws, eid, 0, {"status": "running", "rev": 1}))  # read the same revision, too late
    assert (won, lost) == (True, False)
    # an experiment made before `rev` existed counts as revision 0
    old = new_id()
    run(db.create_experiment(ws, old, {"status": "queued", "tiles": []}))
    assert run(db.update_experiment_if_rev(ws, old, 0, {"rev": 1})) is True
    assert run(db.update_experiment_if_rev(ws, "nosuchexperiment", 0, {"rev": 1})) is False


def test_webhooks_store_list_and_stop_and_a_run_is_claimed_for_an_alert_only_once(ws):
    hid = run(db.create_webhook(ws, {"url": "https://hooks.slack.com/services/T/B/X", "kind": "slack", "include_suspect": False, "created_by": "u"}))
    other = run(db.create_webhook(ws, {"url": "https://example.com/x", "kind": "generic", "include_suspect": True, "created_by": "u"}))
    listed = run(db.list_webhooks(ws))
    assert {h["id"] for h in listed} == {hid, other} and all(h["workspace"] == ws for h in listed)
    assert run(db.revoke_webhook(ws, hid)) is True and run(db.revoke_webhook(ws, hid)) is False
    assert run(db.revoke_webhook("test-someone-else", other)) is False  # another workspace cannot stop it
    rid = new_id()
    run(db.create_run(ws, rid, "w", "t"))
    assert run(db.claim_alert(ws, rid)) is True and run(db.claim_alert(ws, rid)) is False
    assert run(db.claim_alert("test-someone-else", rid)) is False


def test_a_worker_key_that_asked_lately_is_counted_and_one_that_did_not_is_not(ws):
    run(db.create_api_key(ws, "at_live_wrk1", hash_key("wrk1-" + ws), "u", ("worker",)))
    run(db.create_api_key(ws, "at_live_wrk2", hash_key("wrk2-" + ws), "u", ("worker",)))
    run(db.create_api_key(ws, "at_live_ing1", hash_key("ing1-" + ws), "u", ("ingest",)))
    assert run(db.count_workers_since(ws, "2000-01-01T00:00:00+00:00")) == 0  # nobody has asked yet
    for name in ("wrk1", "ing1"):
        run(db.touch_key(run(db.key_for_hash(hash_key(f"{name}-{ws}")))["id"]))
    assert run(db.count_workers_since(ws, "2000-01-01T00:00:00+00:00")) == 1  # one worker; the ingest key does not count
    assert run(db.count_workers_since(ws, "2999-01-01T00:00:00+00:00")) == 0  # asked, but not lately enough
