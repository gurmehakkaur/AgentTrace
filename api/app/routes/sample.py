"""Start with something to fork. Copies the saved example run into the caller's own workspace, step
for step, so a new user can open a real run, fork it and watch a new line open without writing any
code or spending a token. The copy is an ordinary recorded run: the workflow is registered here, so it
is forkable."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.auth import Principal, get_principal
from app.config import get_settings
from app.models import Step
from app.routes.ingest import prepare_step
from app.security import audit
from app.security.limits import import_limiter

router = APIRouter(prefix="/v1")


@router.post("/runs/sample", status_code=201)
async def add_sample_run(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    import_limiter.check(principal.user_id)
    source_ws = get_settings().demo_workspace_id
    source_id = await db.get_featured_run_id(source_ws)
    source = await db.get_run_with_steps(source_ws, source_id) if source_id else None
    if source is None:
        raise HTTPException(status_code=404, detail="The saved example has not been set up on this server yet")

    workspace = principal.org_id
    run_id = uuid.uuid4().hex
    await db.create_run(workspace, run_id, source["workflow"], datetime.now(UTC).isoformat())
    steps = [prepare_step(Step(**{k: v for k, v in s.items() if k in Step.model_fields}), run_id) for s in source["steps"]]
    await db.add_steps(workspace, run_id, steps)
    await db.finish_run(workspace, run_id, "ok", source.get("outcome"), source.get("oracle_detail"))
    await audit.record(workspace, principal.user_id, "run.sample", run_id, {"steps": len(steps)})
    return {"id": run_id, "steps": len(steps)}
