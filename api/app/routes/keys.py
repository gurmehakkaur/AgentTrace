"""Ingest keys: how an organization connects its agents. Admins only. A key is shown exactly once,
when it is made; only its sha256 and a short display prefix are stored."""

import secrets
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import db
from app.auth import KEY_PREFIX, Principal, get_principal, hash_key
from app.security import audit
from app.security.limits import key_limiter

router = APIRouter(prefix="/v1")


def _admin(principal: Principal) -> None:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Only organization admins can manage ingest keys")


class KeyCreate(BaseModel):
    # ingest: send runs. worker: take fork jobs and report them. read: read runs and experiments.
    # spend: start root-cause analyses and experiments, which cost tokens. Default: ingest only.
    scopes: list[Literal["ingest", "worker", "read", "spend"]] = Field(default=["ingest"], min_length=1, max_length=4)


@router.post("/keys", status_code=201)
async def mint_key(body: KeyCreate | None = None, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """Make a key for the caller's organization. The key itself is in this response and nowhere else."""
    scopes = tuple(dict.fromkeys((body or KeyCreate()).scopes))
    _admin(principal)
    key_limiter.check(principal.user_id)
    workspace = principal.org_id
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    await db.upsert_workspace(workspace, workspace)
    await db.create_api_key(workspace, key[:12], hash_key(key), principal.user_id, scopes)
    await audit.record(workspace, principal.user_id, "key.create", key[:12], {"scopes": list(scopes)})
    return {"key": key, "prefix": key[:12], "scopes": list(scopes)}


@router.get("/keys")
async def list_keys(principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    _admin(principal)
    return await db.list_api_keys(principal.org_id)


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: str, principal: Principal = Depends(get_principal)) -> dict[str, str]:
    _admin(principal)
    if not await db.revoke_api_key(principal.org_id, key_id):
        raise HTTPException(status_code=404, detail="Key not found or already revoked")
    await audit.record(principal.org_id, principal.user_id, "key.revoke", key_id)
    return {"id": key_id}
