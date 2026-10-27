"""Run the root-cause agent on a recorded failing run a few times and show the ranking.

    cd api && .venv/bin/python scripts/rca_demo.py --run <run id> --times 3

Reads the run from the dev workspace and calls Claude (Haiku). Nothing is stored.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anthropic import AsyncAnthropic  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.rca.agent import analyze  # noqa: E402
from app.rca.compact import build_prompt  # noqa: E402
from app.rca.lineage import lineage  # noqa: E402
from app.workflows.registry import REGISTRY  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--times", type=int, default=3)
    args = ap.parse_args()

    run = await db.get_run_with_steps(get_settings().dev_workspace_id or "dev", args.run)
    workflow = REGISTRY[run["workflow"]]
    path = lineage(run["steps"], workflow.oracle_keys)
    prompt = build_prompt(run, path, workflow.oracle_keys)
    agent_of = {s["node_run_idx"]: s["agent"] for s in run["steps"]}
    print(f"lineage {path}; prompt ~{len(prompt) // 4} tokens\n")

    client, top = AsyncAnthropic(max_retries=5), []
    outcomes = await asyncio.gather(*(analyze(run, prompt, client) for _ in range(args.times)), return_exceptions=True)
    failed = [o for o in outcomes if isinstance(o, Exception)]
    results = [o for o in outcomes if not isinstance(o, Exception)]
    for f in failed:
        print(f"FAILED call: {type(f).__name__}: {str(f)[:160]}")
    for i, r in enumerate(results, 1):
        ranking = " > ".join(f"{agent_of[c['node_run_idx']]} ({c['confidence']:.2f})" for c in r["candidates"])
        first = r["candidates"][0]
        top.append(agent_of[first["node_run_idx"]])
        print(f"call {i}: {ranking}  [dropped quotes: {r['dropped_quotes']}, tokens {r['tokens_in']}+{r['tokens_out']}]")
    best = results[0]["candidates"][0]
    best_all = results[0]["candidates"]
    print(f"\nexample #1: node run {best['node_run_idx']} step {best['step_idx']}: {best['hypothesis']}")
    print("evidence:", best["evidence_quotes"])
    for c in best_all:
        print(f"  node run {c['node_run_idx']} ({agent_of[c['node_run_idx']]}) proposed_edit: {c['proposed_edit']}")
    print(f"\nplanner ranked #1 in {top.count('planner')} of {args.times} calls ({len(failed)} failed)")


if __name__ == "__main__":
    asyncio.run(main())
