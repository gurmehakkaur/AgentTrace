"""Fork a recorded run at the planner, live, and print each fork's steps and oracle result.

    cd api && .venv/bin/python scripts/fork_demo.py --run <run id> --arm treatment --tries 3
    cd api && .venv/bin/python scripts/fork_demo.py --run <run id> --arm control --tries 3

`treatment` applies the fix (all four open statuses in the planner's ticket filter);
`control` forks at the same point with no edit. Forks are stored in the dev workspace.
Makes real Anthropic calls (Haiku) for every step after the fork point.
"""

import argparse
import asyncio
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anthropic import AsyncAnthropic  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.replay.fork import run_fork  # noqa: E402
from app.workflows.renewal_brief.tools import OPEN_STATUSES, make_tools  # noqa: E402


async def one_fork(ws, run_id, arm, edit, client, tools, i):
    fork_id = await run_fork(ws, run_id, 1, edit, arm, client=client, tools=tools)
    fork = await db.get_run_with_steps(ws, fork_id)
    origins = [s["origin"] for s in fork["steps"]]
    footer = (fork.get("oracle_detail") or {}).get("footer")
    print(f"fork {i} {fork_id[:8]}: {str(fork.get('outcome')).upper():5} origins={origins} footer={footer}")
    return fork.get("outcome") == "pass"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--arm", choices=["control", "treatment"], required=True)
    ap.add_argument("--tries", type=int, default=3)
    args = ap.parse_args()

    ws = get_settings().dev_workspace_id or "dev"
    parent = await db.get_run_with_steps(ws, args.run)
    plan = next(s["state_after"]["plan"] for s in parent["steps"] if s["node_run_idx"] == 1 and s["state_after"])
    edit = None
    if args.arm == "treatment":
        fixed = copy.deepcopy(plan)
        fixed["ticket_filter"]["status"] = list(OPEN_STATUSES)
        edit = {"plan": fixed}
    print(f"parent plan filter: {plan['ticket_filter']}  ->  {'edit: ' + str(edit['plan']['ticket_filter']) if edit else 'no edit (control)'}")

    client, tools = AsyncAnthropic(), make_tools()
    results = await asyncio.gather(
        *(one_fork(ws, args.run, args.arm, edit, client, tools, i + 1) for i in range(args.tries))
    )
    print(f"\n{args.arm}: {sum(results)}/{args.tries} forks passed the oracle")


if __name__ == "__main__":
    asyncio.run(main())
