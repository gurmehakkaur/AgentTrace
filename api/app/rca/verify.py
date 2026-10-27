"""Auto-verify: turn the root-cause agent's opinion into a tested one.

For the top two candidates that propose a concrete edit, run a real experiment (control and
treatment, N=3 each) and re-rank by what was MEASURED, not by the agent's confidence. A candidate is
"verified" only if its treatment beat control (a positive delta) and passed at least 2 of 3 runs.
Candidates the agent gave no concrete edit for cannot be tested, so they stay untested.

Like experiments, this runs as a background task in the API process: it survives the request
but not a server restart.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from agenttrace_sdk import SideEffectBlocked

from app import db
from app.experiments import runner
from app.experiments.runner import view as experiment_view
from app.replay.fork import ModelPinError

log = logging.getLogger(__name__)

N_PER_ARM = 3
MAX_CANDIDATES = 2
MIN_TREATMENT_PASSES = 2
_TASKS: dict[str, asyncio.Task] = {}


def pick_candidates(candidates: list[dict[str, Any]]) -> list[int]:
    """Indexes of the (up to) 2 most confident candidates that carry a testable edit."""
    by_confidence = sorted(range(len(candidates)), key=lambda i: -candidates[i]["confidence"])
    return [i for i in by_confidence if candidates[i].get("proposed_edit")][:MAX_CANDIDATES]


def measure(experiment: dict[str, Any]) -> dict[str, Any]:
    control, treatment = experiment["control"], experiment["treatment"]
    delta = None
    if control["total"] and treatment["total"]:
        delta = treatment["pass"] / treatment["total"] - control["pass"] / control["total"]
    return {
        "status": experiment["status"], "control": control, "treatment": treatment, "delta": delta,
        "verified": experiment["status"] == "done" and delta is not None and delta > 0
        and treatment["pass"] >= MIN_TREATMENT_PASSES,
    }


def rank(items: list[dict[str, Any]], n_candidates: int) -> list[int]:
    """Candidate indexes, best first: verified before not, then larger measured delta, then the
    agent's own order. Untested candidates come after every tested one."""
    tested = {it["candidate_idx"]: it for it in items if it.get("experiment_id")}

    def key(i: int) -> tuple:
        it = tested[i]
        delta = -2.0 if it.get("delta") is None else it["delta"]  # no measurement ranks below any real delta
        return (not it.get("verified"), -delta, i)

    return sorted(tested, key=key) + [i for i in range(n_candidates) if i not in tested]


async def start(
    workspace: str, report: dict[str, Any], *, client: Any, tools: Any, created_by: str
) -> dict[str, Any]:
    """Launch the experiments, record that verification is running, and finish it in the
    background. `report` is the stored report as the API shows it. Raises ValueError if no
    candidate can be tested."""
    picks = pick_candidates(report["candidates"])
    if not picks:
        raise ValueError("no candidate proposes a concrete edit, so there is nothing to test")
    items: list[dict[str, Any]] = []
    for i in picks:
        cand = report["candidates"][i]
        try:
            experiment_id = await runner.create_experiment(
                workspace, report["run"], cand["node_run_idx"], cand["proposed_edit"]["patch"], N_PER_ARM,
                client=client, tools=tools, created_by=created_by,
            )
            items.append({"candidate_idx": i, "experiment_id": experiment_id})
        except (LookupError, ValueError, ModelPinError, SideEffectBlocked) as exc:
            items.append({"candidate_idx": i, "error": str(exc)})  # untestable: say why, test the rest
    if not any(it.get("experiment_id") for it in items):
        raise ValueError(items[0]["error"])

    verification = {"status": "running", "n": N_PER_ARM, "started_at": datetime.now(UTC).isoformat(), "items": items}
    await db.update_rca_report(workspace, report["id"], {"verification": verification})
    task = asyncio.create_task(_finish(workspace, report, verification))
    _TASKS[report["id"]] = task
    task.add_done_callback(lambda _t: _TASKS.pop(report["id"], None))
    return verification


async def _finish(workspace: str, report: dict[str, Any], started: dict[str, Any]) -> None:
    items = started["items"]
    try:
        ids = [it["experiment_id"] for it in items if it.get("experiment_id")]
        await asyncio.gather(*(runner._TASKS[i] for i in ids if i in runner._TASKS), return_exceptions=True)
        done: list[dict[str, Any]] = []
        for it in items:
            if it.get("experiment_id"):
                doc = await db.get_experiment(workspace, it["experiment_id"])
                done.append({**it, **(measure(experiment_view(doc)) if doc else {"status": "error", "verified": False})})
            else:
                done.append(it)
        ranking = rank(done, len(report["candidates"]))
        verified = [it for it in done if it.get("verified")]
        verdict = next((i for i in ranking if any(v["candidate_idx"] == i for v in verified)), None)
        await db.update_rca_report(workspace, report["id"], {
            "verification": {**started, "status": "done", "items": done, "ranking": ranking,
                             "finished_at": datetime.now(UTC).isoformat()},
            "verdict_idx": verdict, "verified_by": [v["experiment_id"] for v in verified],
        })
    except Exception as exc:
        log.error("verification of report %s failed: %s", report["id"], type(exc).__name__)
        await db.update_rca_report(workspace, report["id"], {
            "verification": {**started, "status": "error", "error": type(exc).__name__}
        })
