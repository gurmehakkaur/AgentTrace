"""Phase 12: the generalization benchmark. A fake LLM that reads what it is shown stands in for
Claude: the planner picks its ticket filter by whether the prompt carries the planted bug, the
writer counts what the researcher actually found. So the original prompt fails on accounts with
open tickets, and an account with none passes either way (the table must show that, not hide it)."""

import asyncio
import json
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import db
from app.benchmark import BUG_MARKER, benchmark_view, run_benchmark
from app.main import app
from app.workflows.renewal_brief.tools import OPEN_STATUSES, FixtureTools
from test_public import DEMO, client, make_demo, no_cache  # noqa: F401  (fixtures)
from test_renewal_brief import APPROVE, draft

OPEN = sorted(OPEN_STATUSES)


class SmartLLM:
    """Plans by its prompt, writes from the findings it was given, approves."""

    def __init__(self, crash_on: str | None = None) -> None:
        self.messages = SimpleNamespace(create=self._create)
        self.crash_on = crash_on

    async def _create(self, **kw):
        system, user = kw["system"], kw["messages"][0]["content"]
        if system.startswith("You are the planning agent"):
            account = re.search(r"acct-\d+", user).group(0)
            if self.crash_on == account:
                raise RuntimeError("model unavailable")
            statuses = ["solved"] if BUG_MARKER in system else OPEN
            text = json.dumps({"account_id": account, "ticket_filter": {"status": statuses}})
        elif system.startswith("You are the research agent"):
            text = "summary"
        elif system.startswith("You are the writing agent"):
            findings = json.loads(user.split("Findings:\n", 1)[1].split("\n\n", 1)[0])
            open_n = sum(t["status"] in OPEN_STATUSES for t in findings["tickets"]["tickets"])
            text = draft(open_n, findings["pipeline"]["open_pipeline_usd"])
        elif system.startswith("You are the reviewing agent"):
            text = APPROVE
        else:
            raise AssertionError(f"unexpected prompt: {system[:40]}")
        block = SimpleNamespace(type="text", text=text, model_dump=lambda mode="python": {"type": "text", "text": text})
        return SimpleNamespace(content=[block], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def bench(accounts, n=2, client=None):
    return asyncio.run(run_benchmark(accounts, client or SmartLLM(), FixtureTools(), n=n))


def test_the_original_prompt_fails_and_the_patched_prompt_passes_where_there_are_open_tickets():
    result = bench(["acct-1", "acct-3"])
    for row in result["accounts"]:
        assert row["original"] == {"pass": 0, "total": 2, "errors": 0}
        assert row["patched"] == {"pass": 2, "total": 2, "errors": 0}
    assert result["totals"] == {"original": {"pass": 0, "total": 4}, "patched": {"pass": 4, "total": 4}}


def test_an_account_with_no_open_tickets_passes_either_way_and_is_reported_as_it_is():
    result = bench(["acct-1", "acct-2"])
    by_id = {r["account_id"]: r for r in result["accounts"]}
    assert by_id["acct-2"]["original"]["pass"] == 2 and by_id["acct-2"]["patched"]["pass"] == 2
    assert by_id["acct-1"]["original"]["pass"] == 0
    assert result["totals"]["original"] == {"pass": 2, "total": 4}  # not 0: nothing is massaged


def test_a_run_that_crashes_counts_as_not_passing_and_is_counted_separately():
    result = bench(["acct-1", "acct-3"], client=SmartLLM(crash_on="acct-3"))
    row = {r["account_id"]: r for r in result["accounts"]}["acct-3"]
    assert row["original"] == {"pass": 0, "total": 2, "errors": 2}
    assert row["patched"] == {"pass": 0, "total": 2, "errors": 2}
    assert {r["account_id"]: r for r in result["accounts"]}["acct-1"]["patched"]["pass"] == 2
    assert result["totals"]["patched"] == {"pass": 2, "total": 4}


def test_both_arms_run_n_times_per_account():
    assert bench(["acct-1"], n=3)["accounts"][0]["patched"]["total"] == 3


def test_the_view_has_counts_but_no_ground_truth():
    result = bench(["acct-1"])
    view = benchmark_view({**result, "created_at": "t", "excluded_account": "acct-103", "candidates": [{"x": 1}]})
    assert view["accounts"] == [{"account_id": "acct-1", "original": result["accounts"][0]["original"],
                                 "patched": result["accounts"][0]["patched"]}]
    assert "truth" not in json.dumps(view) and "candidates" not in view
    assert view["excluded_account"] == "acct-103"
    assert benchmark_view(None) is None


# --- the routes ------------------------------------------------------------------------------

def store_benchmark(workspace, experiment_id, result=None):
    asyncio.run(db.create_benchmark(workspace, "b1", {
        "experiment": experiment_id, "workflow": "renewal_brief", "created_at": "2026-10-23T00:00:00+00:00",
        "excluded_account": "acct-103", **(result or bench(["acct-1", "acct-2"])),
    }))


def test_the_public_demo_shows_the_hero_benchmark_and_nothing_for_the_decoy(client, store):
    _, ids = make_demo(store)
    hero_id = ids[0]
    store_benchmark(DEMO, hero_id)
    by_role = {e["role"]: e for e in client.get("/v1/public/demo").json()["experiments"]}
    assert by_role["hero"]["benchmark"]["totals"]["patched"] == {"pass": 4, "total": 4}
    assert by_role["decoy"]["benchmark"] is None


def test_an_experiment_without_a_benchmark_says_so(client, store):
    make_demo(store)
    assert all(e["benchmark"] is None for e in client.get("/v1/public/demo").json()["experiments"])


def test_a_workspace_only_sees_its_own_benchmark(store, login):
    _, ids = make_demo(store, ws="ws-a")
    store_benchmark("ws-a", ids[0])
    login("ws-a")
    assert TestClient(app).get(f"/v1/experiments/{ids[0]}").json()["benchmark"]["n"] == 2
    login("ws-b")
    assert TestClient(app).get(f"/v1/experiments/{ids[0]}").status_code == 404
    # a benchmark stored under another workspace's name for the same experiment id is never returned
    assert asyncio.run(db.get_benchmark_for_experiment("ws-b", ids[0])) is None


def test_deleting_the_run_deletes_its_benchmark(store):
    run_id, ids = make_demo(store, ws="ws-a")
    store_benchmark("ws-a", ids[0])
    asyncio.run(db.delete_run_cascade("ws-a", run_id))
    assert store.benchmarks == []
