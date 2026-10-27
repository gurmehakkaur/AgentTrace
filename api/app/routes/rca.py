"""Root-cause analysis of a failed run: POST runs it (and stores the report), GET returns the
latest stored report. Scoped to the caller's workspace."""

from typing import Any

from agenttrace_sdk import SideEffectBlocked
from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.auth import Principal, get_principal, read_workspace
from app.rca.agent import RcaError
from app.rca.report import report_view
from app.rca import verify
from app.rca.service import generate_report
from app.replay.fork import ModelPinError
from app.runtime import get_runtime
from app.security import audit
from app.security.limits import enforce_daily_cap, experiment_limiter, launch_lock, rca_limiter
from app.workflows.registry import REGISTRY

router = APIRouter(prefix="/v1")


async def run_rca(workspace: str, user_id: str, run_id: str, runtime: tuple[Any, Any]) -> dict[str, Any]:
    """Root-cause a failed run for `user_id` (a person, or `key:<id>`): same limit, same checks, same audit."""
    rca_limiter.check(user_id)
    run = await db.get_run_with_steps(workspace, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("outcome") != "fail":
        raise HTTPException(status_code=409, detail="Root-cause analysis is for runs that failed the oracle")
    workflow = REGISTRY.get(run["workflow"])
    if workflow is None:
        raise HTTPException(status_code=422, detail=f"workflow {run['workflow']!r} is not registered")

    try:
        report = await generate_report(workspace, run, workflow, runtime[0])
    except RcaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    await audit.record(workspace, user_id, "rca.run", run_id, {"report": report["id"]})
    return report


@router.post("/runs/{run_id}/rca")
async def create_rca(
    run_id: str, principal: Principal = Depends(get_principal), runtime: tuple[Any, Any] = Depends(get_runtime)
) -> dict[str, Any]:
    return await run_rca(principal.org_id, principal.user_id, run_id, runtime)


@router.get("/runs/{run_id}/rca")
async def get_rca(run_id: str, workspace: str = Depends(read_workspace)) -> dict[str, Any]:
    doc = await db.get_latest_rca_report(workspace, run_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="No root-cause report for this run yet")
    return report_view(doc)


@router.post("/runs/{run_id}/rca/verify", status_code=202)
async def verify_rca(
    run_id: str, principal: Principal = Depends(get_principal), runtime: tuple[Any, Any] = Depends(get_runtime)
) -> dict[str, Any]:
    """Test the top candidates of the latest report with real experiments (N=3 per arm) and re-rank
    them by measured effect. Starts the experiments and returns at once; poll GET .../rca."""
    workspace = principal.org_id
    experiment_limiter.check(principal.user_id)
    stored = await db.get_latest_rca_report(workspace, run_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Run the root-cause analysis first")
    report = report_view(stored)
    if (report["verification"] or {}).get("status") == "running":
        raise HTTPException(status_code=409, detail="This analysis is already being verified")
    testable = len(verify.pick_candidates(report["candidates"]))
    if testable == 0:
        raise HTTPException(status_code=422, detail="No candidate proposes a concrete edit, so there is nothing to test")

    client, tools = runtime
    try:
        async with launch_lock:
            await enforce_daily_cap(principal.user_id, needed=testable)  # each tested candidate is an experiment
            verification = await verify.start(workspace, report, client=client, tools=tools, created_by=principal.user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except (ModelPinError, SideEffectBlocked) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    await audit.record(workspace, principal.user_id, "rca.verify", report["id"], {
        "run": run_id, "experiments": [it["experiment_id"] for it in verification["items"] if it.get("experiment_id")],
    })
    return {"report": report["id"], "verification": verification}
