"""Run an experiment: the same fork point twice, control (no edit) and treatment (the edit),
N live suffixes each, scored by the oracle. Results are k/N per arm plus a Fisher exact
p-value, always labelled "directional": live steps are sampled, never deterministic.

Experiments run as asyncio tasks inside the API process. They outlive the HTTP request that
started them but NOT a process restart (a production version would use a worker and a queue);
an experiment interrupted by a restart stays 'running' forever.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agenttrace_sdk import redact

from app import alerts, db
from app.config import get_settings
from app.experiments.stats import fisher_exact_two_sided, wilson
from app.rca.memory import is_verified, remember_experiment
from app.rca.report import report_view
from app.replay.fork import prepare_fork, run_fork
from app.workflows.registry import REGISTRY

log = logging.getLogger(__name__)

CONCURRENCY = 3  # parallel fork suffixes per experiment, to stay under rate limits
_TASKS: dict[str, asyncio.Task] = {}  # keeps a reference so running tasks are not garbage-collected


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stats(doc: dict[str, Any]) -> dict[str, Any]:
    c, t = doc["control"], doc["treatment"]
    done = c["total"] > 0 and t["total"] > 0
    return {
        "fisher_p": fisher_exact_two_sided(t["pass"], t["total"] - t["pass"], c["pass"], c["total"] - c["pass"])
        if done else None,
        "wilson": {"control": wilson(c["pass"], c["total"]), "treatment": wilson(t["pass"], t["total"])},
        # Directional, never proof: say so wherever these numbers are shown.
        "label": f"directional evidence, N={doc['n']}",
    }


def view(doc: dict[str, Any]) -> dict[str, Any]:
    """An experiment as the API returns it. SurrealDB drops fields stored as None, so the
    optional tile fields are put back here."""
    tiles = [
        {"arm": t["arm"], "i": t["i"], "status": t["status"],
         "run_id": t.get("run_id"), "outcome": t.get("outcome")}
        for t in doc["tiles"]
    ]
    return {
        "id": doc["id"], "status": doc["status"], "parent_run": doc["parent_run"],
        "fork_node_run_idx": doc["fork_idx"], "n": doc["n"], "edit_patch": doc["edit_patch"],
        "control": doc["control"], "treatment": doc["treatment"], "tiles": tiles,
        "stats": doc.get("stats") or _stats(doc),
        "tokens_used": doc["tokens_used"], "token_ceiling": doc["token_ceiling"],
        "error": doc.get("error"), "created_at": doc.get("created_at"),
        # "worker": run by the customer's own worker, which is waiting for jobs while the experiment is queued.
        "mode": doc.get("mode", "server"),
    }


async def create_experiment(
    workspace: str, parent_run_id: str, fork_node_run_idx: int, edit: dict[str, Any], n: int,
    *, client: Any, tools: Any, created_by: str,
) -> str:
    """Validate, store the experiment as 'queued', start it in the background, return its id.

    Raises what prepare_fork raises (LookupError, ValueError, ModelPinError, SideEffectBlocked),
    and ValueError if n is outside 1..MAX_N, all before anything is created.
    """
    settings = get_settings()
    if not 1 <= n <= settings.max_n:
        raise ValueError(f"n must be between 1 and {settings.max_n}")
    parent = await db.get_run_with_steps(workspace, parent_run_id)
    if parent is not None and parent["workflow"] not in REGISTRY:
        # Not one of ours to run: the customer's worker runs it. Same checks on the fork point, no live run here.
        from app.experiments import worker  # noqa: PLC0415 (worker imports this module)

        return await worker.create(workspace, {**parent, "id": parent_run_id}, fork_node_run_idx, edit, n, created_by)
    await prepare_fork(workspace, parent_run_id, fork_node_run_idx, edit, tools)

    experiment_id = uuid4().hex
    # Control and treatment interleaved, so a token cap leaves the two arms balanced.
    tiles = [{"arm": arm, "i": i, "status": "queued"} for i in range(1, n + 1) for arm in ("control", "treatment")]
    stored_edit, _ = redact(edit)
    doc = {
        "parent_run": parent_run_id, "fork_idx": fork_node_run_idx, "edit_mode": "output",
        "edit_patch": stored_edit, "n": n, "control": {"pass": 0, "total": 0},
        "treatment": {"pass": 0, "total": 0}, "tiles": tiles, "status": "queued",
        "tokens_used": 0, "token_ceiling": settings.max_tokens_per_experiment,
        "created_by": created_by, "created_at": _now(),
    }
    await db.create_experiment(workspace, experiment_id, doc)

    task = asyncio.create_task(_run(workspace, experiment_id, doc, edit, client, tools))
    _TASKS[experiment_id] = task
    task.add_done_callback(lambda _t: _TASKS.pop(experiment_id, None))
    return experiment_id


async def _run(
    workspace: str, experiment_id: str, doc: dict[str, Any], edit: dict[str, Any], client: Any, tools: Any
) -> None:
    gate, lock = asyncio.Semaphore(CONCURRENCY), asyncio.Lock()
    skipped = False

    async def persist(**extra: Any) -> None:
        async with lock:
            await db.update_experiment(workspace, experiment_id, {
                "status": doc["status"], "tiles": doc["tiles"], "control": doc["control"],
                "treatment": doc["treatment"], "tokens_used": doc["tokens_used"], **extra,
            })

    async def one(tile: dict[str, Any]) -> None:
        nonlocal skipped
        async with gate:
            if doc["tokens_used"] >= doc["token_ceiling"]:
                tile["status"], skipped = "skipped", True
                await persist()
                return
            tile["status"] = "running"
            await persist()
            arm, outcome, tokens = tile["arm"], "error", 0
            try:
                run_id = await run_fork(
                    workspace, doc["parent_run"], doc["fork_idx"], edit if arm == "treatment" else None,
                    arm, client=client, tools=tools, experiment_id=experiment_id,
                )
                tile["run_id"] = run_id
                summary = await db.get_run_summary(workspace, run_id) or {}
                outcome = summary.get("outcome") or "error"
                tokens = (summary.get("tokens_in") or 0) + (summary.get("tokens_out") or 0)
                await db.create_tested_edge(experiment_id, run_id)
            except Exception as exc:  # a fork that could not even start counts as an error run
                log.warning("experiment %s fork failed: %s", experiment_id, type(exc).__name__)
            tile["status"], tile["outcome"] = "done", outcome
            counts = doc[arm]
            counts["total"] += 1  # errors count as runs that did not pass
            counts["pass"] += outcome == "pass"
            doc["tokens_used"] += tokens
            await persist()

    try:
        doc["status"] = "running"
        await persist()
        await asyncio.gather(*(one(t) for t in doc["tiles"]))
        doc["status"] = "capped" if skipped else "done"
        doc["stats"] = _stats(doc)
        await persist(stats=doc["stats"], finished_at=_now())
        await alerts.notify_experiment(workspace, experiment_id)
        if doc["status"] == "done":
            await _remember(workspace, experiment_id, doc)
    except Exception as exc:
        log.error("experiment %s failed: %s", experiment_id, type(exc).__name__)
        doc["status"] = "error"
        await persist(error=type(exc).__name__)


async def _remember(workspace: str, experiment_id: str, doc: dict[str, Any]) -> None:
    """Store a verified experiment's root cause in Agent Memory. Best effort: whatever goes wrong
    here, the experiment has already finished and its result stands."""
    try:
        shown = view({**doc, "id": experiment_id})
        if not is_verified(shown["control"], shown["treatment"]):
            return
        run = await db.get_run_with_steps(workspace, doc["parent_run"])
        stored_report = await db.get_latest_rca_report(workspace, doc["parent_run"])
        report = report_view(stored_report) if stored_report else None
        scope = await remember_experiment(workspace, shown, run, report) if run is not None else None
        if scope:
            await db.update_experiment(workspace, experiment_id, {"remembered": True, "memory_scope": scope})
    except Exception as exc:
        log.warning("experiment %s: could not remember pattern: %s", experiment_id, type(exc).__name__)
