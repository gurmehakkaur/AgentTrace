"""Browser -> API reads. Scoped to the caller's workspace; another workspace's run is a 404."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app import db
from app.auth import Principal, get_principal, read_workspace
from app.experiments.runner import view as experiment_view
from app.rca.memory import forget_scopes
from app.security import audit
from app.workflows.registry import REGISTRY

router = APIRouter(prefix="/v1")

MAX_FORK_DEPTH = 4  # forks of forks of forks...: enough to read, and it bounds the work


@router.get("/runs")
async def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    kind: Literal["recorded", "fork"] | None = Query(default=None, description="recorded leaves out fork attempts"),
    workspace: str = Depends(read_workspace),
) -> list[dict[str, Any]]:
    return await db.list_runs(workspace, limit, kind)


@router.get("/runs/{run_id}")
async def get_run(run_id: str, workspace: str = Depends(read_workspace)) -> dict[str, Any]:
    run = await db.get_run_with_steps(workspace, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    # A registered workflow is re-run here. Any other run can still be forked by the customer's own worker,
    # if it recorded the state after an agent turn and the keys that turn wrote. Otherwise it is view only.
    if run["workflow"] in REGISTRY:
        mode = "server"
    elif any(s.get("state_after") and s.get("writes") for s in run["steps"]):
        mode = "worker"
    else:
        mode = None
    return {**run, "forkable": mode is not None, "fork_mode": mode}


@router.get("/runs/{run_id}/experiments")
async def list_run_experiments(run_id: str, workspace: str = Depends(read_workspace)) -> list[dict[str, Any]]:
    """The forks of this run, each as its experiment: they are drawn as branches of the run."""
    if not await db.run_exists(workspace, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    # A fork can itself be forked, so follow the runs each fork made: its branches have branches.
    found: list[dict[str, Any]] = []
    frontier = [run_id]
    for _ in range(MAX_FORK_DEPTH):
        level = await db.list_experiments_for_runs(workspace, frontier)
        if not level:
            break
        found += level
        frontier = [t["run_id"] for e in level for t in e.get("tiles", []) if t.get("run_id")]
    return [experiment_view(e) for e in sorted(found, key=lambda e: e.get("created_at", ""))]


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """Admins only. Deletes the run, every fork of it, their steps, the experiments run on them,
    root-cause reports, and what Agent Memory remembered from them. The audit record is written
    first and must succeed: deleting data never goes unrecorded."""
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Only organization admins can delete runs")
    workspace = principal.org_id
    if not await db.run_exists(workspace, run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    await audit.record(workspace, principal.user_id, "run.delete", run_id, strict=True)
    deleted = await db.delete_run_cascade(workspace, run_id)
    if deleted is None:  # deleted by someone else between the check and now
        raise HTTPException(status_code=404, detail="Run not found")

    forgotten, failed = await forget_scopes(deleted["memory_scopes"])
    if failed:  # the run is gone, but some remembered patterns may remain: say so, do not hide it
        await audit.record(workspace, principal.user_id, "run.delete.memory_incomplete", run_id,
                           {"scopes_failed": failed})
    return {
        "deleted": {k: deleted[k] for k in ("runs", "steps", "experiments", "rca_reports")},
        "memory": {"items_forgotten": forgotten, "scopes_not_forgotten": failed},
    }
