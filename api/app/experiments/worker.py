"""Experiments run by the customer's own worker.

A workflow that is not registered here cannot be re-run by this server: its agents are the customer's code.
So for such a run an experiment is created as a list of jobs (a control job and a treatment job, N each) and
a worker the customer runs, next to their code, claims them one at a time, runs the rest of the workflow
live, and reports what happened. This server then does what it always does: records each attempt as a fork
run (the steps before the fork point replayed exactly from the recording, the rest live), counts k/N per
arm, and works out the Fisher p-value, labelled directional.

The worker connects out to us; we never connect in. It holds a key with the `worker` scope.

Claims are taken with compare-and-set on the experiment's `rev`, so two workers cannot take the same job. A
claim lasts LEASE_SECONDS; if the worker vanishes the job goes back in the queue (MAX_ATTEMPTS times, then it
counts as an error run). The token ceiling applies to what workers report.
"""

import copy
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from agenttrace_sdk import redact
from fastapi import HTTPException

from app import alerts, db
from app.config import get_settings
from app.experiments.runner import _remember, _stats
from app.models import WorkerResult
from app.replay.fork import _copy, _edited_step
from app.routes.ingest import prepare_step

log = logging.getLogger(__name__)

LEASE_SECONDS = 600
MAX_ATTEMPTS = 3
_RETRIES = 6  # a lost race re-reads and tries again


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _tile(doc: dict[str, Any], arm: str, i: int) -> dict[str, Any] | None:
    return next((t for t in doc["tiles"] if t["arm"] == arm and t["i"] == i), None)


async def create(
    workspace: str, parent: dict[str, Any], fork_node_run_idx: int, edit: dict[str, Any], n: int, created_by: str,
) -> str:
    """Store an experiment for a worker to run. Raises ValueError for a fork point that cannot be restored."""
    steps, k = parent["steps"], fork_node_run_idx
    node_k = [s for s in steps if s["node_run_idx"] == k]
    if not node_k:
        raise ValueError(f"parent run has no node run {k}")
    state = node_k[-1]["state_after"]
    if not isinstance(state, dict):
        raise ValueError(f"node run {k} has no recorded state_after to restore, so it cannot be forked")
    undeclared = sorted(set(edit) - set(node_k[-1]["writes"]))
    if undeclared:
        raise ValueError(f"edit keys {undeclared} are not writes of node run {k}")

    settings = get_settings()
    prefix_last = max((s["idx"] for s in steps if s["node_run_idx"] < k), default=0)
    stored_edit, _ = redact(edit)
    experiment_id = uuid.uuid4().hex
    doc = {
        "mode": "worker", "workflow": parent["workflow"], "rev": 0,
        "parent_run": parent["id"], "fork_idx": k, "edit_mode": "output", "edit_patch": stored_edit, "n": n,
        "base_state": state,  # what the live part starts from (already redacted when it was recorded)
        "start_idx": prefix_last + 1,  # the edited step takes this number; live steps continue after it
        "control": {"pass": 0, "total": 0}, "treatment": {"pass": 0, "total": 0},
        "tiles": [{"arm": arm, "i": i, "status": "queued"} for i in range(1, n + 1) for arm in ("control", "treatment")],
        "status": "queued", "tokens_used": 0, "token_ceiling": settings.max_tokens_per_experiment,
        "created_by": created_by, "created_at": _now(),
    }
    await db.create_experiment(workspace, experiment_id, doc)
    return experiment_id


def _reap(doc: dict[str, Any]) -> bool:
    """Put jobs whose worker went quiet back in the queue. A job that has used up its attempts is an error run."""
    changed = False
    cutoff = datetime.now(UTC) - timedelta(seconds=LEASE_SECONDS)
    for t in doc["tiles"]:
        if t["status"] != "running" or datetime.fromisoformat(t.get("claimed_at", _now())) > cutoff:
            continue
        changed = True
        if t.get("attempts", 1) >= MAX_ATTEMPTS:
            t.update(status="done", outcome="error")
            doc[t["arm"]]["total"] += 1
        else:
            t.update(status="queued")
        t.pop("claim", None)
    return changed


def _finish(doc: dict[str, Any]) -> bool:
    """Close the experiment when no job is left. True if it just closed."""
    if any(t["status"] in ("queued", "running") for t in doc["tiles"]):
        return False
    doc["status"] = "capped" if any(t["status"] == "skipped" for t in doc["tiles"]) else "done"
    doc["stats"] = _stats(doc)
    doc["finished_at"] = _now()
    return True


async def claim(workspace: str, workflows: list[str], worker: str) -> dict[str, Any] | None:
    """The next job for a worker that can run `workflows`, or None."""
    async with db.session():
        return await _claim(workspace, workflows, worker)


async def _claim(workspace: str, workflows: list[str], worker: str) -> dict[str, Any] | None:
    for _ in range(_RETRIES):
        docs = [
            copy.deepcopy(d) for d in await db.list_experiments(workspace)
            if d.get("mode") == "worker" and d["status"] in ("queued", "running") and d.get("workflow") in workflows
        ]
        raced = False
        for doc in sorted(docs, key=lambda d: d.get("created_at", "")):
            rev = doc.get("rev") or 0
            changed = _reap(doc)
            if doc["tokens_used"] >= doc["token_ceiling"]:  # the ceiling holds for what workers report, too
                for t in doc["tiles"]:
                    if t["status"] == "queued":
                        t["status"] = "skipped"
                        changed = True
            tile = next((t for t in doc["tiles"] if t["status"] == "queued"), None)
            if tile is not None:
                tile.update(status="running", claim=uuid.uuid4().hex, claimed_at=_now(), attempts=tile.get("attempts", 0) + 1, worker=worker)
                doc["status"], changed = "running", True
            if not changed:
                continue
            closed = _finish(doc) if tile is None else False
            patch = {k: doc[k] for k in ("status", "tiles", "control", "treatment", "tokens_used")} | {"rev": rev + 1}
            if closed:
                patch |= {"stats": doc["stats"], "finished_at": doc["finished_at"]}
            if not await db.update_experiment_if_rev(workspace, doc["id"], rev, patch):
                raced = True
                break
            if tile is not None:
                state = {**doc["base_state"], **doc["edit_patch"]} if tile["arm"] == "treatment" else doc["base_state"]
                return {
                    "claim": tile["claim"], "experiment": doc["id"], "arm": tile["arm"], "i": tile["i"],
                    "workflow": doc["workflow"], "parent_run": doc["parent_run"], "fork_node_run_idx": doc["fork_idx"],
                    "state": state, "lease_seconds": LEASE_SECONDS,
                }
        if not raced:
            return None
    return None


async def report(workspace: str, body: WorkerResult) -> dict[str, Any]:
    """Record one finished job as a fork run and count it. Safe to send twice."""
    async with db.session():
        return await _report(workspace, body)


async def _report(workspace: str, body: WorkerResult) -> dict[str, Any]:
    doc = await db.get_experiment(workspace, body.experiment)
    if doc is None or doc.get("mode") != "worker":
        raise HTTPException(status_code=404, detail="Experiment not found")
    tile = _tile(doc, body.arm, body.i)
    if tile is None:
        raise HTTPException(status_code=404, detail="No such job in this experiment")
    if tile["status"] == "done":
        return {"recorded": False, "detail": "already recorded"}
    if tile["status"] != "running" or tile.get("claim") != body.claim:
        raise HTTPException(status_code=409, detail="This job is not claimed by you any more. Its time ran out, or another worker took it.")

    run_id = uuid.uuid4().hex
    parent = await db.get_run_with_steps(workspace, doc["parent_run"])
    if parent is None:
        raise HTTPException(status_code=404, detail="The run this experiment was made from is gone")
    k, start_idx = doc["fork_idx"], doc["start_idx"]
    node_k = [s for s in parent["steps"] if s["node_run_idx"] == k]
    treatment = body.arm == "treatment"
    copied = [_copy(s, run_id, "replayed") for s in parent["steps"] if s["node_run_idx"] < k]
    if treatment:
        state = {**doc["base_state"], **doc["edit_patch"]}
        copied.append(_edited_step(run_id, start_idx, k, node_k[-1], doc["edit_patch"], state))
        last_idx = start_idx
    else:
        copied += [_copy(s, run_id, "replayed") for s in node_k]
        last_idx = max(s["idx"] for s in copied)
    live = []
    for s in body.steps:  # the worker numbers its turns from 1; they go after the fork point
        placed = s.model_copy(update={"idx": last_idx + s.idx, "node_run_idx": k + s.node_run_idx, "origin": "live"})
        live.append(prepare_step(placed, run_id))

    started = _now()
    await db.create_run(workspace, run_id, doc["workflow"], started, kind="fork")
    await db.add_steps(workspace, run_id, copied + live)
    await db.create_fork_edge(workspace, run_id, doc["parent_run"], k, body.arm, body.experiment)
    await db.finish_run(workspace, run_id, "ok", body.outcome, body.oracle_detail)
    await db.create_tested_edge(body.experiment, run_id)
    tokens = sum(s.tokens_in + s.tokens_out for s in body.steps)

    for _ in range(_RETRIES):
        doc = await db.get_experiment(workspace, body.experiment)
        tile = _tile(doc, body.arm, body.i)
        if tile["status"] == "done":
            return {"recorded": False, "detail": "already recorded"}
        rev = doc.get("rev") or 0
        tile.update(status="done", run_id=run_id, outcome=body.outcome)
        tile.pop("claim", None)
        doc[body.arm]["total"] += 1  # an error counts as a run that did not pass
        doc[body.arm]["pass"] += body.outcome == "pass"
        doc["tokens_used"] += tokens
        closed = _finish(doc)
        patch = {k_: doc[k_] for k_ in ("status", "tiles", "control", "treatment", "tokens_used")} | {"rev": rev + 1}
        if closed:
            patch |= {"stats": doc["stats"], "finished_at": doc["finished_at"]}
        if await db.update_experiment_if_rev(workspace, body.experiment, rev, patch):
            if closed:
                await alerts.notify_experiment(workspace, body.experiment)
            if closed and doc["status"] == "done":
                await _remember(workspace, body.experiment, copy.deepcopy(doc))
            return {"recorded": True, "run": run_id}
    raise HTTPException(status_code=503, detail="Too many workers reporting at once. Send the result again.")
