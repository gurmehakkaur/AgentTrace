"""The customer's worker talks to us here. It holds a key with the `worker` scope, claims one job at a time and
reports it. It only ever calls out; this API never calls the worker. The workspace comes from the key."""

import time
from typing import Any

from fastapi import APIRouter, Depends

from app import db
from app.auth import KeyPrincipal, key_with_scope
from app.experiments import worker
from app.models import WorkerClaim, WorkerResult
from app.security import audit

router = APIRouter(prefix="/v1/worker")

SEEN_EVERY_S = 20  # a worker asks every few seconds: note it now and then, not on every ask
ONLINE_FOR_S = 60  # a worker that asked within this long ago counts as connected
_noted: dict[str, float] = {}


@router.post("/claim")
async def claim(body: WorkerClaim, key: KeyPrincipal = Depends(key_with_scope("worker"))) -> dict[str, Any]:
    """The next job for a worker that can run these workflows, or `{"job": null}` when there is none."""
    if time.monotonic() - _noted.get(key.key_id, -SEEN_EVERY_S) >= SEEN_EVERY_S:
        _noted[key.key_id] = time.monotonic()
        await db.touch_key(key.key_id)
    return {"job": await worker.claim(key.workspace, body.workflows, body.worker)}


@router.post("/results")
async def result(body: WorkerResult, key: KeyPrincipal = Depends(key_with_scope("worker"))) -> dict[str, Any]:
    out = await worker.report(key.workspace, body)
    if out["recorded"]:
        await audit.record(key.workspace, key.user_id, "worker.result", body.experiment, {"arm": body.arm, "outcome": body.outcome})
    return out
