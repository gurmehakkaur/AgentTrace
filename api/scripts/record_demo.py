"""Record one renewal-brief run into AgentTrace through the SDK's HttpSink.

    cd api && .venv/bin/python scripts/record_demo.py              # the failing (buggy) run
    cd api && .venv/bin/python scripts/record_demo.py --prompt good

Needs the API running (AGENTTRACE_API_URL) and AGENTTRACE_INGEST_KEY from
scripts/create_workspace_key.py. Makes real Anthropic calls (Haiku).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agenttrace_sdk import HttpSink, trace_run  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.runner.run import run_to_end  # noqa: E402
from app.workflows.renewal_brief.graph import next_node  # noqa: E402
from app.workflows.renewal_brief.nodes import build_nodes  # noqa: E402
from app.workflows.renewal_brief.oracle import check, ground_truth  # noqa: E402
from app.workflows.renewal_brief.prompts import PLANNER_SYSTEM_BUGGY, PLANNER_SYSTEM_GOOD  # noqa: E402
from app.workflows.renewal_brief.tools import make_tools  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", choices=["good", "buggy"], default="buggy")
    args = ap.parse_args()

    base = os.environ.get("AGENTTRACE_API_URL", "http://localhost:8000")
    key = os.environ.get("AGENTTRACE_INGEST_KEY", "")
    if not key:
        sys.exit("AGENTTRACE_INGEST_KEY is empty: run scripts/create_workspace_key.py first")

    account = get_settings().demo_account_id
    tools = make_tools()
    truth = await ground_truth(tools, account)
    nodes = build_nodes(PLANNER_SYSTEM_GOOD if args.prompt == "good" else PLANNER_SYSTEM_BUGGY)
    state = {"request": f"Write a renewal risk brief for account {account}."}

    async with trace_run("renewal_brief", HttpSink(base, key)) as run:
        final = await run_to_end(nodes, next_node, state, AsyncAnthropic(), tools)
        passed, detail = check(final, truth)
        run.outcome, run.oracle_detail = ("pass" if passed else "fail"), detail

    print(f"run {run.id}: {run.outcome.upper()}  footer={detail['footer']}  truth={truth}")
    print(f"read it back: GET {base}/v1/runs/{run.id}")


if __name__ == "__main__":
    asyncio.run(main())
