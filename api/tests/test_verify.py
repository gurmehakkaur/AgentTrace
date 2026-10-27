"""Phase 12a: auto-verify. The agent's top candidates are tested with real experiments (N=3) and
re-ranked by what was measured. Offline: the fake LLM makes the planner fix work and the critic
decoy fail, with the DECOY given the higher confidence, so only measurement can get the order right."""

import time

import pytest
from fastapi.testclient import TestClient

from app.auth import get_principal
from app.main import app
from app.rca import verify
from app.runtime import get_runtime
from test_experiments import FakeLLM, FixtureTools
from test_fork import FIXED_PLAN, WS, record
from test_renewal_brief import APPROVE, BUGGY_PLAN, draft

PLANNER_EDIT = {"mode": "output", "patch": FIXED_PLAN}
CRITIC_DECOY = {"mode": "output", "patch": {"verdict": "revise", "feedback": "verify the counts"}}


def candidate(node_run_idx, step_idx, confidence, edit):
    return {"node_run_idx": node_run_idx, "step_idx": step_idx, "confidence": confidence, "hypothesis": f"h{node_run_idx}",
            "evidence_quotes": [], "proposed_edit": edit, "matches_past_pattern": None}


@pytest.fixture
def failed_run(store):
    run_id = record(BUGGY_PLAN, "No open tickets.", draft(0), APPROVE)
    store.runs[run_id].update(outcome="fail", oracle_detail={"open_tickets_ok": False})
    return run_id


def save_report(store, run_id, candidates, **extra):
    import asyncio
    asyncio.run(store.create_rca_report(WS, "r1", {"run": run_id, "lineage": [1], "created_at": "2026-01-01T00:00:00Z",
                                                   "model": "m", "tokens_in": 1, "tokens_out": 1, "candidates": candidates, **extra}))


@pytest.fixture
def api(store, login):
    login("ws-a", "member", "user_1")
    app.dependency_overrides[get_runtime] = lambda: (FakeLLM(), FixtureTools())
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_runtime, None)


def wait_verified(api, run_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        report = api.get(f"/v1/runs/{run_id}/rca").json()
        if report["verification"] and report["verification"]["status"] != "running":
            return report
        time.sleep(0.05)
    raise AssertionError("verification did not finish")


# --- pure logic ------------------------------------------------------------------------------

def test_the_two_most_confident_candidates_with_an_edit_are_picked():
    cands = [candidate(3, 5, 0.95, None), candidate(4, 6, 0.9, CRITIC_DECOY), candidate(1, 1, 0.5, PLANNER_EDIT), candidate(2, 2, 0.4, PLANNER_EDIT)]
    assert verify.pick_candidates(cands) == [1, 2]  # the 0.95 one has no edit to test
    assert verify.pick_candidates([candidate(3, 5, 0.9, None)]) == []


@pytest.mark.parametrize(
    ("control", "treatment", "status", "delta", "verified"),
    [
        ({"pass": 0, "total": 3}, {"pass": 3, "total": 3}, "done", 1.0, True),
        ({"pass": 0, "total": 3}, {"pass": 2, "total": 3}, "done", pytest.approx(2 / 3), True),
        ({"pass": 0, "total": 3}, {"pass": 1, "total": 3}, "done", pytest.approx(1 / 3), False),  # fewer than 2 passes
        ({"pass": 3, "total": 3}, {"pass": 3, "total": 3}, "done", 0.0, False),  # no better than control
        ({"pass": 0, "total": 3}, {"pass": 0, "total": 3}, "done", 0.0, False),  # the decoy
        ({"pass": 0, "total": 3}, {"pass": 3, "total": 3}, "capped", 1.0, False),  # an incomplete experiment never verifies
        ({"pass": 0, "total": 0}, {"pass": 0, "total": 0}, "error", None, False),
    ],
)
def test_measure_requires_a_positive_delta_two_passes_and_a_finished_experiment(control, treatment, status, delta, verified):
    m = verify.measure({"control": control, "treatment": treatment, "status": status})
    assert m["delta"] == delta and m["verified"] is verified


def test_rank_puts_verified_first_then_larger_delta_then_untested_last():
    items = [
        {"candidate_idx": 0, "experiment_id": "a", "verified": False, "delta": 0.0},
        {"candidate_idx": 2, "experiment_id": "b", "verified": True, "delta": 0.67},
        {"candidate_idx": 3, "experiment_id": "c", "verified": True, "delta": 1.0},
        {"candidate_idx": 4, "error": "could not test"},
    ]
    assert verify.rank(items, 6) == [3, 2, 0, 1, 4, 5]


# --- the whole flow through the API ----------------------------------------------------------

def test_measurement_beats_confidence_the_decoy_loses_and_the_planner_is_the_verdict(api, store, failed_run):
    save_report(store, failed_run, [
        candidate(4, 6, 0.9, CRITIC_DECOY),  # the agent's favourite: a stricter critic
        candidate(1, 1, 0.5, PLANNER_EDIT),  # the real cause, ranked lower by the agent
        candidate(3, 5, 0.4, None),  # the writer: a symptom, no edit to test
    ])
    resp = api.post(f"/v1/runs/{failed_run}/rca/verify")
    assert resp.status_code == 202 and len(resp.json()["verification"]["items"]) == 2

    report = wait_verified(api, failed_run)
    v = report["verification"]
    by_idx = {it["candidate_idx"]: it for it in v["items"]}
    assert by_idx[0]["control"] == {"pass": 0, "total": 3} and by_idx[0]["treatment"] == {"pass": 0, "total": 3}
    assert by_idx[0]["verified"] is False and by_idx[0]["delta"] == 0
    assert by_idx[1]["treatment"] == {"pass": 3, "total": 3} and by_idx[1]["verified"] is True and by_idx[1]["delta"] == 1.0
    assert v["ranking"] == [1, 0, 2] and report["verdict_idx"] == 1  # the planner, not the confident decoy
    assert report["verified_by"] == [by_idx[1]["experiment_id"]]
    assert v["status"] == "done" and v["n"] == 3


def test_verification_launches_real_experiments_audits_and_counts_against_the_daily_cap(api, store, failed_run):
    save_report(store, failed_run, [candidate(4, 6, 0.9, CRITIC_DECOY), candidate(1, 1, 0.5, PLANNER_EDIT)])
    api.post(f"/v1/runs/{failed_run}/rca/verify")
    wait_verified(api, failed_run)

    mine = [e for e in store.experiments.values() if e["created_by"] == "user_1"]
    assert len(mine) == 2 and {e["n"] for e in mine} == {3} and {e["status"] for e in mine} == {"done"}
    assert [a for a in store.audit if a["action"] == "rca.verify"][0]["detail"]["run"] == failed_run


def test_the_daily_cap_must_have_room_for_every_experiment_it_would_start(api, store, failed_run, monkeypatch):
    monkeypatch.setenv("DAILY_EXPERIMENTS_PER_USER", "1")
    save_report(store, failed_run, [candidate(4, 6, 0.9, CRITIC_DECOY), candidate(1, 1, 0.5, PLANNER_EDIT)])
    resp = api.post(f"/v1/runs/{failed_run}/rca/verify")
    assert resp.status_code == 429 and "Daily experiment limit" in resp.json()["detail"]
    assert store.experiments == {}  # nothing was started


def test_a_candidate_that_cannot_be_tested_is_reported_and_the_rest_still_run(api, store, failed_run):
    bad = {"mode": "output", "patch": {"not_a_key_this_node_writes": 1}}
    save_report(store, failed_run, [candidate(4, 6, 0.9, bad), candidate(1, 1, 0.5, PLANNER_EDIT)])
    api.post(f"/v1/runs/{failed_run}/rca/verify")
    report = wait_verified(api, failed_run)
    by_idx = {it["candidate_idx"]: it for it in report["verification"]["items"]}
    assert "not writes of node run 4" in by_idx[0]["error"] and by_idx[1]["verified"] is True
    assert report["verification"]["ranking"] == [1, 0] and report["verdict_idx"] == 1


def test_no_verdict_when_nothing_beats_control(api, store, failed_run):
    save_report(store, failed_run, [candidate(4, 6, 0.9, CRITIC_DECOY)])
    api.post(f"/v1/runs/{failed_run}/rca/verify")
    report = wait_verified(api, failed_run)
    assert report["verdict_idx"] is None and report["verified_by"] == [] and report["verification"]["ranking"] == [0]


def test_refusals(api, store, failed_run, login):
    assert api.post(f"/v1/runs/{failed_run}/rca/verify").status_code == 404  # no analysis yet
    save_report(store, failed_run, [candidate(3, 5, 0.9, None)])
    assert api.post(f"/v1/runs/{failed_run}/rca/verify").status_code == 422  # nothing testable
    store.rca_reports[0]["candidates"] = [candidate(1, 1, 0.5, PLANNER_EDIT)]
    store.rca_reports[0]["verification"] = {"status": "running", "items": []}
    assert api.post(f"/v1/runs/{failed_run}/rca/verify").status_code == 409  # already running
    login("ws-b", "member")
    assert api.post(f"/v1/runs/{failed_run}/rca/verify").status_code == 404  # another workspace
    app.dependency_overrides.pop(get_principal)
    assert api.post(f"/v1/runs/{failed_run}/rca/verify").status_code == 401
