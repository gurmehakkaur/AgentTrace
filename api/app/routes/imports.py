"""Import past runs. Two doors, one job: a signed-in person (the web app) or a script holding an
ingest key. Either way the workspace comes from the credential, never from the body."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends

from app import alerts
from app.auth import Principal, get_principal, ingest_workspace
from app.importer import ImportRun, import_run
from app.security import audit
from app.security.limits import import_limiter

router = APIRouter(prefix="/v1")


@router.post("/runs/import", status_code=201)
async def import_as_member(body: ImportRun, background: BackgroundTasks, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    import_limiter.check(principal.user_id)
    result = await import_run(principal.org_id, body)
    await audit.record(principal.org_id, principal.user_id, "run.import", result["id"], {"steps": result["steps"]})
    if body.outcome in ("fail", "error"):
        background.add_task(alerts.notify_failure, principal.org_id, result["id"])
    return result


@router.post("/import", status_code=201)
async def import_with_key(body: ImportRun, background: BackgroundTasks, workspace: str = Depends(ingest_workspace)) -> dict[str, Any]:
    result = await import_run(workspace, body)
    if body.outcome in ("fail", "error"):
        background.add_task(alerts.notify_failure, workspace, result["id"])
    return result
