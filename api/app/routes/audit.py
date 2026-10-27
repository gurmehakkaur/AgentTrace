"""The workspace's audit log, for organization admins."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app import db
from app.auth import Principal, get_principal

router = APIRouter(prefix="/v1")


@router.get("/audit")
async def get_audit(
    limit: int = Query(default=100, ge=1, le=500), principal: Principal = Depends(get_principal)
) -> list[dict[str, Any]]:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Only organization admins can read the audit log")
    return await db.list_audit(principal.org_id, limit)
