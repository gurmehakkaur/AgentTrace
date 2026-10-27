"""Run the renewal brief N times and print oracle pass counts.

    cd api && .venv/bin/python scripts/run_demo.py --prompt good --times 5
    cd api && .venv/bin/python scripts/run_demo.py --prompt buggy --times 3

Makes real Anthropic calls (Haiku). Uses TOOLS_BACKEND and DEMO_ACCOUNT_ID from .env.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agenttrace_sdk import ListSink, trace_run  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.runner.run import run_to_end  # noqa: E402
from app.workflows.renewal_brief.graph import next_node  # noqa: E402
from app.workflows.renewal_brief.nodes import build_nodes  # noqa: E402
from app.workflows.renewal_brief.oracle import check, ground_truth  # noqa: E402
from app.workflows.renewal_brief.prompts import PLANNER_SYSTEM_BUGGY, PLANNER_SYSTEM_GOOD  # noqa: E402
from app.workflows.renewal_brief.tools import make_tools  # noqa: E402


async def one_run(i: int, prompt: str, client, tools, truth, account_id: str, gate) -> bool:
    nodes = build_nodes(PLANNER_SYSTEM_GOOD if prompt == "good" else PLANNER_SYSTEM_BUGGY)
    state = {"request": f"Write a renewal risk brief for account {account_id}."}
    sink = ListSink()
    async with gate:
        try:
            async with trace_run("renewal_brief", sink):
                final = await run_to_end(nodes, next_node, state, client, tools)
        except Exception as exc:  # a crashed run is a failed run
            print(f"run {i}: ERROR {type(exc).__name__}: {str(exc)[:120]}")
            return False
    passed, detail = check(final, truth)
    tokens = sum(s["tokens_in"] + s["tokens_out"] for s in sink.steps)
    got = detail["footer"] and {k: detail["footer"].get(k) for k in ("open_tickets", "open_pipeline_usd")}
    print(f"run {i}: {'PASS' if passed else 'FAIL'}  got={got}  drafts={detail['drafts']}  tokens={tokens}")
    return passed


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", choices=["good", "buggy"], required=True)
    ap.add_argument("--times", type=int, default=3)
    args = ap.parse_args()

    settings = get_settings()
    tools, client = make_tools(), AsyncAnthropic()
    truth = await ground_truth(tools, settings.demo_account_id)
    print(f"backend={settings.tools_backend} account={settings.demo_account_id} truth={truth}")

    gate = asyncio.Semaphore(3)
    results = await asyncio.gather(
        *(one_run(i + 1, args.prompt, client, tools, truth, settings.demo_account_id, gate)
          for i in range(args.times))
    )
    print(f"\n{args.prompt} prompt: {sum(results)}/{args.times} passed the oracle")


if __name__ == "__main__":
    asyncio.run(main())
