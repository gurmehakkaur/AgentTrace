"""Seed the public demo workspace so visitors see real results without spending tokens.

    cd api && .venv/bin/python scripts/seed_demo.py

Records the planted-bug run 3 times and keeps the cleanest one (it failed the oracle, has a valid
footer, no revision loop, fewest steps), asks the root-cause agent about it, then runs two
experiments side by side: the DECOY (a stricter critic: the obvious fix, which does not help) and
the HERO (the planner's ticket filter, as the root-cause agent proposes). Everything is stored
under DEMO_WORKSPACE_ID and marked featured; the numbers shown are whatever the experiments
actually produced. Re-running replaces the featured set (older runs stay, un-featured).

Real Anthropic calls (Haiku) and real Era data: roughly 150k-200k tokens, about 5 minutes.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agenttrace_sdk import trace_run  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.experiments import runner  # noqa: E402
from app.rca.service import generate_report  # noqa: E402
from app.runner.run import run_to_end  # noqa: E402
from app.runner.sink import DbSink  # noqa: E402
from app.workflows.registry import REGISTRY  # noqa: E402
from app.workflows.renewal_brief.graph import next_node  # noqa: E402
from app.workflows.renewal_brief.nodes import build_nodes  # noqa: E402
from app.workflows.renewal_brief.oracle import check, ground_truth  # noqa: E402
from app.workflows.renewal_brief.prompts import PLANNER_SYSTEM_BUGGY  # noqa: E402
from app.workflows.renewal_brief.tools import OPEN_STATUSES, make_tools  # noqa: E402

DECOY_FEEDBACK = "Verify the open-ticket count against the raw data."


async def record_one(ws, client, tools, account):
    state = {"request": f"Write a renewal risk brief for account {account}."}
    async with trace_run("renewal_brief", DbSink(ws)) as r:
        final = await run_to_end(build_nodes(PLANNER_SYSTEM_BUGGY), next_node, state, client, tools)
        passed, detail = check(final, await ground_truth(tools, account))
        r.outcome, r.oracle_detail = ("pass" if passed else "fail"), detail
    return await db.get_run_with_steps(ws, r.id)


def cleanliness(run):
    """Sort key for 'cleanest': must have failed, with a parsed footer and no revision loop."""
    detail = run.get("oracle_detail") or {}
    ok = run.get("outcome") == "fail" and detail.get("footer") and detail.get("drafts") == 1
    return (0 if ok else 1, len(run["steps"]), (run.get("tokens_in") or 0) + (run.get("tokens_out") or 0))


async def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    settings = get_settings()
    ws, account = settings.demo_workspace_id, settings.demo_account_id
    client, tools = AsyncAnthropic(max_retries=5), make_tools()
    print(f"seeding workspace {ws!r}, account {account}, tools={settings.tools_backend}")

    await db.apply_schema()
    await db.upsert_workspace(ws, "Public demo")

    # 1. record the failing run three times, keep the cleanest
    runs = [r for r in await asyncio.gather(*(record_one(ws, client, tools, account) for _ in range(3)),
                                            return_exceptions=True) if isinstance(r, dict)]
    runs.sort(key=cleanliness)
    if not runs or cleanliness(runs[0])[0] != 0:
        sys.exit("none of the 3 recordings was a clean failure; nothing featured (re-run to retry)")
    run = runs[0]
    print(f"recorded {len(runs)} runs; keeping {run['id'][:8]} ({len(run['steps'])} steps, "
          f"footer {run['oracle_detail']['footer']}, truth {run['oracle_detail']['truth']})")

    # 2. root-cause analysis
    report = await generate_report(ws, run, REGISTRY[run["workflow"]], client)
    top = report["candidates"][0]
    agent_of = {s["node_run_idx"]: s["agent"] for s in run["steps"]}
    print(f"RCA: #1 is {agent_of[top['node_run_idx']]} at {top['confidence']:.0%}; "
          f"edit proposed: {bool(top['proposed_edit'])}")

    # 3. the two experiments. Hero uses the agent's proposed fix when it targets the planner.
    planner_idx = next(i for i, a in agent_of.items() if a == "planner")
    critic_idx = max(i for i, a in agent_of.items() if a == "critic")
    plan = next(s["state_after"]["plan"] for s in run["steps"] if s["node_run_idx"] == planner_idx and s["state_after"])
    proposed = top["proposed_edit"] if top["node_run_idx"] == planner_idx and top["proposed_edit"] else None
    hero_edit = proposed["patch"] if proposed else {"plan": {**plan, "ticket_filter": {"status": list(OPEN_STATUSES)}}}
    print("hero edit:", "the root-cause agent's proposal" if proposed else "fallback: the four open statuses")
    decoy_edit = {"verdict": "revise", "feedback": DECOY_FEEDBACK}

    decoy_id = await runner.create_experiment(ws, run["id"], critic_idx, decoy_edit, 5,
                                              client=client, tools=tools, created_by="seed")
    hero_id = await runner.create_experiment(ws, run["id"], planner_idx, hero_edit, 8,
                                             client=client, tools=tools, created_by="seed")
    print("running both experiments (about 4 minutes)...")
    await asyncio.gather(runner._TASKS[decoy_id], runner._TASKS[hero_id])

    # 4. feature it all
    await db.clear_featured(ws)
    await db.set_run_featured(ws, run["id"])
    for role, exp_id in (("decoy", decoy_id), ("hero", hero_id)):
        await db.update_experiment(ws, exp_id, {"featured": True, "demo_role": role})
        e = runner.view(await db.get_experiment(ws, exp_id))
        print(f"{role:5}: control {e['control']['pass']}/{e['control']['total']} -> treatment "
              f"{e['treatment']['pass']}/{e['treatment']['total']}  p={e['stats']['fisher_p']}  "
              f"status={e['status']}  tokens={e['tokens_used']}")
    print("featured run:", run["id"])


if __name__ == "__main__":
    asyncio.run(main())
