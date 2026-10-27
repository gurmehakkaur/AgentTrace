"""Generalization benchmark: does the planner fix work on accounts other than the demo one?

For each account, run the WHOLE workflow N times with the original (buggy) planner prompt and N
times with the patched one, and count how often the code oracle passes. Unlike an experiment this
is not a fork: every run is a fresh end-to-end run, so it tests the prompt fix, not one edit.
Era supplies the data and the exact ground truth for every account, which is why a pass count
means something. Results are reported as they come out."""

import asyncio
from typing import Any

from app.runner.run import run_to_end
from app.workflows.renewal_brief.graph import next_node
from app.workflows.renewal_brief.nodes import build_nodes
from app.workflows.renewal_brief.oracle import check, ground_truth
from app.workflows.renewal_brief.prompts import BUG_LINE, PLANNER_SYSTEM_BUGGY, PLANNER_SYSTEM_GOOD

BUG_MARKER = BUG_LINE  # what the original prompt carries and the patched one does not
ARMS = {"original": PLANNER_SYSTEM_BUGGY, "patched": PLANNER_SYSTEM_GOOD}


async def _one(prompt: str, account_id: str, truth: dict[str, Any], client: Any, tools: Any) -> str:
    state = {"request": f"Write a renewal risk brief for account {account_id}."}
    try:
        final = await run_to_end(build_nodes(prompt), next_node, state, client, tools)
        return "pass" if check(final, truth)[0] else "fail"
    except Exception:  # a run that crashes did not pass; it is counted, not hidden
        return "error"


async def run_benchmark(
    account_ids: list[str], client: Any, tools: Any, n: int = 3, concurrency: int = 3
) -> dict[str, Any]:
    gate = asyncio.Semaphore(concurrency)
    truths = {a: await ground_truth(tools, a) for a in account_ids}

    async def run(arm: str, account_id: str) -> tuple[str, str, str]:
        async with gate:
            return arm, account_id, await _one(ARMS[arm], account_id, truths[account_id], client, tools)

    outcomes = await asyncio.gather(*(run(arm, a) for a in account_ids for arm in ARMS for _ in range(n)))
    accounts = []
    for a in account_ids:
        row: dict[str, Any] = {"account_id": a, "truth": truths[a]}
        for arm in ARMS:
            results = [o for arm_, acct, o in outcomes if arm_ == arm and acct == a]
            row[arm] = {"pass": results.count("pass"), "total": len(results), "errors": results.count("error")}
        accounts.append(row)
    totals = {arm: {"pass": sum(r[arm]["pass"] for r in accounts), "total": sum(r[arm]["total"] for r in accounts)}
              for arm in ARMS}
    return {"n": n, "accounts": accounts, "totals": totals}


def benchmark_view(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """A stored benchmark as the API returns it (no ground truth values, just the counts)."""
    if doc is None:
        return None
    return {
        "n": doc["n"], "created_at": doc.get("created_at"), "excluded_account": doc.get("excluded_account"),
        "accounts": [{"account_id": a["account_id"], "original": a["original"], "patched": a["patched"]}
                     for a in doc["accounts"]],
        "totals": doc["totals"],
    }
