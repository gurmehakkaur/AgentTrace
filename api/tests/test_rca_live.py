"""Phase 9 'Done when', for real: record the planted-bug run with live Claude, then ask the RCA
agent about it 3 times. The planner must be ranked #1 in at least 2 of the 3 calls, and its top
candidate must carry a concrete fix for the plan.

    RUN_LIVE=1 api/.venv/bin/pytest api/tests/test_rca_live.py

Uses SurrealDB and Anthropic (Haiku, a few cents) in a throwaway test-* workspace."""

import asyncio
import os
import uuid

import pytest
from agenttrace_sdk import trace_run
from anthropic import AsyncAnthropic

from app import db
from app.config import get_settings
from app.rca.agent import analyze
from app.rca.compact import build_prompt
from app.rca.lineage import lineage
from app.runner.run import run_to_end
from app.runner.sink import DbSink
from app.workflows.registry import REGISTRY
from app.workflows.renewal_brief.graph import next_node
from app.workflows.renewal_brief.nodes import build_nodes
from app.workflows.renewal_brief.oracle import check, ground_truth
from app.workflows.renewal_brief.prompts import PLANNER_SYSTEM_BUGGY
from app.workflows.renewal_brief.tools import make_tools

pytestmark = pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 (spends tokens)")


def test_planner_is_ranked_first_in_at_least_two_of_three_calls():
    ws = f"test-{uuid.uuid4().hex[:8]}"
    client, tools = AsyncAnthropic(max_retries=5), make_tools()
    account = get_settings().demo_account_id

    async def go():
        await db.apply_schema()
        state = {"request": f"Write a renewal risk brief for account {account}."}
        async with trace_run("renewal_brief", DbSink(ws)) as r:
            final = await run_to_end(build_nodes(PLANNER_SYSTEM_BUGGY), next_node, state, client, tools)
            passed, detail = check(final, await ground_truth(tools, account))
            r.outcome, r.oracle_detail = ("pass" if passed else "fail"), detail
        run = await db.get_run_with_steps(ws, r.id)
        assert run["outcome"] == "fail", "the planted bug should make the run fail"

        workflow = REGISTRY[run["workflow"]]
        prompt = build_prompt(run, lineage(run["steps"], workflow.oracle_keys), workflow.oracle_keys)
        agent_of = {s["node_run_idx"]: s["agent"] for s in run["steps"]}
        results = await asyncio.gather(*(analyze(run, prompt, client) for _ in range(3)))
        return agent_of, results

    try:
        agent_of, results = asyncio.run(go())
    finally:
        asyncio.run(db.purge_workspace(ws))

    tops = [agent_of[r["candidates"][0]["node_run_idx"]] for r in results]
    assert tops.count("planner") >= 2, tops
    planner_edit = next(r["candidates"][0]["proposed_edit"] for r in results if agent_of[r["candidates"][0]["node_run_idx"]] == "planner")
    assert planner_edit and "plan" in planner_edit["patch"]
