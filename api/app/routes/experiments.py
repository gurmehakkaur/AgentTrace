"""Start an experiment (returns immediately) and poll it. Scoped to the caller's workspace."""

from datetime import UTC, datetime, timedelta
from typing import Any

from agenttrace_sdk import SideEffectBlocked
from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.benchmark import benchmark_view
from app.auth import Principal, get_principal, read_workspace
from app.experiments.runner import create_experiment, view
from app.models import ExperimentCreate
from app.replay.fork import ModelPinError
from app.runtime import get_runtime
from app.security import audit
from app.security.limits import enforce_daily_cap, experiment_limiter, launch_lock

router = APIRouter(prefix="/v1")


async def launch(workspace: str, user_id: str, body: ExperimentCreate, runtime: tuple[Any, Any]) -> str:
    """Start an experiment for `user_id` (a person, or `key:<id>` for an API key): the same limits, the same
    errors and the same audit record whoever asks."""
    client, tools = runtime
    experiment_limiter.check(user_id)
    try:
        async with launch_lock:
            await enforce_daily_cap(user_id)
            experiment_id = await create_experiment(
                workspace, body.run_id, body.fork_node_run_idx, body.edit, body.n,
                client=client, tools=tools, created_by=user_id,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except (ModelPinError, SideEffectBlocked) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    await audit.record(workspace, user_id, "experiment.launch", experiment_id, {
        "parent_run": body.run_id, "fork_node_run_idx": body.fork_node_run_idx, "n": body.n,
        "edit_keys": sorted(body.edit),
    })
    return experiment_id


@router.post("/experiments", status_code=202)
async def start_experiment(
    body: ExperimentCreate,
    principal: Principal = Depends(get_principal),
    runtime: tuple[Any, Any] = Depends(get_runtime),
) -> dict[str, str]:
    return {"id": await launch(principal.org_id, principal.user_id, body, runtime)}


@router.get("/experiments")
async def list_experiments(workspace: str = Depends(read_workspace)) -> list[dict[str, Any]]:
    """Every fork in the workspace, for the project timeline."""
    experiments = await db.list_experiments(workspace)
    agents = await db.agents_for_runs(sorted({e["parent_run"] for e in experiments}))
    # The agent each fork changed, so a list of forks can say "planner" and not "agent step 1".
    return [{**view(e), "fork_agent": agents.get(e["parent_run"], {}).get(e["fork_idx"])} for e in experiments]


async def workers_online(workspace: str, doc: dict[str, Any]) -> int | None:
    """How many of the workspace's workers asked for a job lately. Only for an experiment a worker runs."""
    if doc.get("mode") != "worker":
        return None
    from app.routes.worker import ONLINE_FOR_S  # noqa: PLC0415
    since = (datetime.now(UTC) - timedelta(seconds=ONLINE_FOR_S)).isoformat()
    return await db.count_workers_since(workspace, since)


@router.get("/experiments/{experiment_id}")
async def get_experiment(experiment_id: str, workspace: str = Depends(read_workspace)) -> dict[str, Any]:
    doc = await db.get_experiment(workspace, experiment_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return {**view(doc), "benchmark": benchmark_view(await db.get_benchmark_for_experiment(workspace, experiment_id)),
            "workers_online": await workers_online(workspace, doc)}
