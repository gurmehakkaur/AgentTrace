"""Read-only demo content for people who are not signed in (judges, visitors).

The workspace is fixed by server configuration (DEMO_WORKSPACE_ID, default "demo"):
it never comes from the request, so these routes cannot be pointed at anyone else's data.
There are no write endpoints here. Responses are cached in memory and by the browser, so a
crowd cannot turn into a stream of database queries."""

import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from app import db
from app.benchmark import benchmark_view
from app.config import get_settings
from app.experiments.runner import view
from app.rca.report import report_view

router = APIRouter(prefix="/v1/public")

CACHE_TTL_S = 60.0
_cache: dict[str, tuple[float, Any]] = {}
_ROLE_ORDER = {"decoy": 0, "hero": 1}  # the story: the obvious fix fails, then the real fix works


async def _cached(key: str, load: Callable[[], Awaitable[Any]]) -> Any:
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    value = await load()  # a 404 raises here, so errors are never cached
    _cache[key] = (time.monotonic() + CACHE_TTL_S, value)
    return value


@router.get("/demo")
async def demo(response: Response) -> dict[str, Any]:
    """The featured failing run, its root-cause report, and the featured experiments."""
    workspace = get_settings().demo_workspace_id

    async def load() -> dict[str, Any]:
        run_id = await db.get_featured_run_id(workspace)
        run = await db.get_run_with_steps(workspace, run_id) if run_id else None
        if run is None:
            raise HTTPException(status_code=404, detail="The demo has not been seeded yet")
        report = await db.get_latest_rca_report(workspace, run_id)
        experiments = sorted(
            await db.list_featured_experiments(workspace), key=lambda e: _ROLE_ORDER.get(e.get("demo_role"), 9)
        )
        return {
            "run": {**run, "forkable": False},  # the public example is read only
            "rca": report_view(report) if report else None,
            "experiments": [
                {"role": e.get("demo_role"), **view(e),
                 "benchmark": benchmark_view(await db.get_benchmark_for_experiment(workspace, e["id"]))}
                for e in experiments
            ],
        }

    payload = await _cached("demo", load)
    response.headers["Cache-Control"] = "public, max-age=60"
    return payload


@router.get("/demo/runs/{run_id}")
async def demo_run(run_id: str, response: Response) -> dict[str, Any]:
    """Any run in the demo workspace (the featured run's experiment forks link here)."""
    workspace = get_settings().demo_workspace_id

    async def load() -> dict[str, Any]:
        run = await db.get_run_with_steps(workspace, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    payload = await _cached(f"run:{run_id}", load)
    response.headers["Cache-Control"] = "public, max-age=60"
    return payload
