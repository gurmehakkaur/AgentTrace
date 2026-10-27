"""SDK -> API. Authenticated by a per-workspace ingest key; every call is scoped to that
key's workspace. Safe to retry: run creation and step insertion are idempotent. Payloads are
redacted again here and clamped to 32 KB per text field."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app import alerts, db
from app.auth import ingest_workspace
from app.models import RunCreate, RunFinish, Step, StepBatch
from app.security.limits import clamp_strings
from agenttrace_sdk import redact

router = APIRouter(prefix="/v1")


def prepare_step(step: Step, run_id: str) -> dict[str, Any]:
    """Re-redact (the SDK may be misconfigured) and pin the step to the run in the URL."""
    doc = step.model_dump()
    earlier = doc.pop("redactions")
    clean, found = redact(doc)
    clean = clamp_strings(clean)  # no stored text field is longer than 32 KB
    clean["run"] = run_id
    clean["redactions"] = earlier + found
    return clean


@router.post("/runs", status_code=201)
async def create_run(body: RunCreate, workspace: str = Depends(ingest_workspace)) -> dict[str, str]:
    try:
        await db.create_run(workspace, body.id, body.workflow, body.started_at)
    except db.RunConflict:
        raise HTTPException(status_code=409, detail="Run id already in use") from None
    return {"id": body.id}


@router.post("/runs/{run_id}/steps")
async def add_steps(
    run_id: str, body: StepBatch, workspace: str = Depends(ingest_workspace)
) -> dict[str, int]:
    if not await db.run_exists(workspace, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    steps = [prepare_step(s, run_id) for s in body.steps]
    return {"received": len(steps), "added": await db.add_steps(workspace, run_id, steps)}


@router.post("/runs/{run_id}/finish")
async def finish_run(
    run_id: str, body: RunFinish, background: BackgroundTasks, workspace: str = Depends(ingest_workspace)
) -> dict[str, str]:
    detail, _ = redact(body.oracle_detail) if body.oracle_detail is not None else (None, [])
    if not await db.finish_run(workspace, run_id, body.status, body.outcome, detail):
        raise HTTPException(status_code=404, detail="Run not found")
    if body.outcome in ("fail", "error"):
        background.add_task(alerts.notify_failure, workspace, run_id)  # after the answer: an alert never delays a run
    return {"id": run_id, "status": body.status}
