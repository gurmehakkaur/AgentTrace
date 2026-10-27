"""Phase 11 against the REAL Agent Memory context. Skipped unless RUN_LIVE=1 and the SPECTRON_*
variables are set:

    RUN_LIVE=1 api/.venv/bin/pytest api/tests/test_memory_live.py

Uses a throwaway test-* workspace (so a throwaway scope) and removes what it stored."""

import asyncio
import os
import time
import uuid

import pytest
from agenttrace_sdk import trace_run
from anthropic import AsyncAnthropic

from app import db
from app.config import get_settings
from app.rca import memory
from app.rca.service import generate_report
from app.runner.run import run_to_end
from app.runner.sink import DbSink
from app.workflows.registry import REGISTRY
from app.workflows.renewal_brief.graph import next_node
from app.workflows.renewal_brief.nodes import build_nodes
from app.workflows.renewal_brief.oracle import check, ground_truth
from app.workflows.renewal_brief.prompts import PLANNER_SYSTEM_BUGGY
from app.workflows.renewal_brief.tools import make_tools

pytestmark = pytest.mark.skipif(
    not (os.environ.get("RUN_LIVE") and get_settings().memory_configured),
    reason="set RUN_LIVE=1 and the SPECTRON_* variables",
)


def poll(coro_fn, ready, tries=8, wait=3.0):
    """Memory may index a moment after remember(): poll until `ready(result)`."""
    result = None
    for _ in range(tries):
        result = asyncio.run(coro_fn())
        if ready(result):
            return result
        time.sleep(wait)
    return result


def synthetic_experiment(run_id):
    return {"id": uuid.uuid4().hex, "parent_run": run_id, "fork_node_run_idx": 1, "n": 3,
            "edit_patch": {"plan": {}}, "control": {"pass": 0, "total": 3}, "treatment": {"pass": 3, "total": 3},
            "stats": {"fisher_p": 0.1}}


async def record_failing_run(ws, client, tools, account):
    state = {"request": f"Write a renewal risk brief for account {account}."}
    async with trace_run("renewal_brief", DbSink(ws)) as r:
        final = await run_to_end(build_nodes(PLANNER_SYSTEM_BUGGY), next_node, state, client, tools)
        passed, detail = check(final, await ground_truth(tools, account))
        r.outcome, r.oracle_detail = ("pass" if passed else "fail"), detail
    return await db.get_run_with_steps(ws, r.id)


async def register_in_db(ws, exp, scope):
    """What the experiment runner does after remembering: keep the scope so recall can find it."""
    await db.apply_schema()
    await db.create_experiment(ws, exp["id"], {"remembered": True, "memory_scope": scope,
                                               "finished_at": "2026-01-01T00:00:00+00:00"})


def test_remember_recall_and_forget_round_trip_with_provenance():
    ws = f"test-{uuid.uuid4().hex[:8]}"
    run = {"id": uuid.uuid4().hex, "workflow": "renewal_brief", "oracle_detail": {"open_tickets_ok": False},
           "steps": [{"node_run_idx": 1, "agent": "planner"}]}
    exp = synthetic_experiment(run["id"])
    try:
        scope = asyncio.run(memory.remember_experiment(ws, exp, run, None))
        assert scope == memory.run_scope(ws, "renewal_brief", run["id"])
        asyncio.run(register_in_db(ws, exp, scope))

        found = poll(lambda: memory.recall_patterns(ws, "renewal_brief", ["open_tickets"]), bool)
        assert [f["experiment"] for f in found] == [exp["id"]] and found[0]["run"] == run["id"]
        assert asyncio.run(memory.recall_patterns("test-someone-else", "renewal_brief", ["open_tickets"])) == []

        assert asyncio.run(memory.forget_run(ws, "renewal_brief", run["id"])) >= 1
        assert poll(lambda: memory.recall_patterns(ws, "renewal_brief", ["open_tickets"]), lambda r: not r) == []
    finally:
        asyncio.run(memory.forget_run(ws, "renewal_brief", run["id"]))
        asyncio.run(db.purge_workspace(ws))


def test_a_second_failing_run_gets_seen_before_with_a_link_to_the_earlier_experiment():
    """The Done-when: remembered pattern -> a freshly recorded failing run -> RCA recalls it, the
    agent claims the match, and the report links the earlier experiment."""
    ws = f"test-{uuid.uuid4().hex[:8]}"
    client, tools, account = AsyncAnthropic(max_retries=5), make_tools(), get_settings().demo_account_id

    async def first_failure():
        await db.apply_schema()
        run = await record_failing_run(ws, client, tools, account)
        assert run["outcome"] == "fail"
        exp = synthetic_experiment(run["id"])
        scope = await memory.remember_experiment(ws, exp, run, None)
        assert scope, "the verified pattern should be stored"
        await register_in_db(ws, exp, scope)
        return exp, run["id"]

    async def second_failure():
        run = await record_failing_run(ws, client, tools, account)
        return await generate_report(ws, run, REGISTRY[run["workflow"]], client)

    first_run = None
    try:
        exp, first_run = asyncio.run(first_failure())
        poll(lambda: memory.recall_patterns(ws, "renewal_brief", ["open_tickets"]), bool)
        report = asyncio.run(second_failure())
        assert [r["experiment"] for r in report["recalled"]] == [exp["id"]]
        matches = [c for c in report["candidates"] if c["matches_past_pattern"] == exp["id"]]
        assert matches, "the agent should recognise the pattern it was shown"
        import re
        assert re.search(r"seen before|earlier|past|previous|prior", matches[0]["hypothesis"], re.I), matches[0]["hypothesis"]
    finally:
        if first_run:
            asyncio.run(memory.forget_run(ws, "renewal_brief", first_run))
        asyncio.run(db.purge_workspace(ws))
