"""Phase 5 'Done when', for real: record the planted-bug run with live Claude, then fork at the
planner with the fixed filter. At least one of 3 tries must pass the oracle.

    RUN_LIVE=1 api/.venv/bin/pytest api/tests/test_fork_live.py

Uses SurrealDB, Anthropic (Haiku, a few cents) and TOOLS_BACKEND from .env, in a throwaway
test-* workspace that is purged afterwards."""

import asyncio
import copy
import os
import uuid

import pytest
from agenttrace_sdk import trace_run
from anthropic import AsyncAnthropic

from app import db
from app.replay.fork import run_fork
from app.runner.run import run_to_end
from app.runner.sink import DbSink
from app.workflows.renewal_brief.graph import next_node
from app.workflows.renewal_brief.nodes import build_nodes
from app.config import get_settings
from app.workflows.renewal_brief.prompts import PLANNER_SYSTEM_BUGGY
from app.workflows.renewal_brief.tools import OPEN_STATUSES, make_tools

pytestmark = pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 (spends tokens)")


def test_planner_fork_with_the_fixed_filter_passes_the_oracle_at_least_once_in_three_tries():
    ws = f"test-{uuid.uuid4().hex[:8]}"
    client, tools = AsyncAnthropic(), make_tools()
    account = get_settings().demo_account_id

    async def go():
        await db.apply_schema()
        async with trace_run("renewal_brief", DbSink(ws)) as r:
            await run_to_end(build_nodes(PLANNER_SYSTEM_BUGGY), next_node,
                             {"request": f"Write a renewal risk brief for account {account}."}, client, tools)
        parent = await db.get_run_with_steps(ws, r.id)
        plan = next(s["state_after"]["plan"] for s in parent["steps"] if s["node_run_idx"] == 1)
        fixed = copy.deepcopy(plan)
        fixed["ticket_filter"]["status"] = list(OPEN_STATUSES)

        outcomes = []
        for _ in range(3):
            fork_id = await run_fork(ws, r.id, 1, {"plan": fixed}, "treatment", client=client, tools=tools)
            fork = await db.get_run_with_steps(ws, fork_id)
            outcomes.append(fork["outcome"])
            origins = [s["origin"] for s in fork["steps"]]
            assert origins[0] == "edited" and set(origins[1:]) == {"live"}
            if fork["outcome"] == "pass":
                break
        return outcomes

    try:
        assert "pass" in asyncio.run(go())
    finally:
        asyncio.run(db.purge_workspace(ws))
