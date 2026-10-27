"""Alert webhooks: where to tell people when a run fails. Organization admins only. The address is a secret
(a Slack address lets anyone post), so listing shows only its host and last four characters."""

import secrets
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import alerts, db
from app.auth import Principal, get_principal
from app.security import audit
from app.security.limits import webhook_limiter

router = APIRouter(prefix="/v1")

MAX_WEBHOOKS = 5


class WebhookCreate(BaseModel):
    url: str = Field(min_length=12, max_length=500)
    kind: Literal["slack", "generic"] = "slack"
    include_suspect: bool = False  # costs tokens for each failed run of a registered workflow
    on_forks: bool = True  # also tell me when a fork (an experiment) finishes, with its result


def _admin(principal: Principal) -> None:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Only organization admins can manage alert webhooks")


def _shown(h: dict[str, Any]) -> dict[str, Any]:
    url = h["url"]
    return {"id": h["id"], "kind": h["kind"], "host": alerts.urlsplit(url).hostname, "ends": url[-4:],
            "include_suspect": bool(h.get("include_suspect")), "on_forks": h.get("on_forks", True), "created_at": h.get("created_at"), "revoked_at": h.get("revoked_at")}


@router.post("/webhooks", status_code=201)
async def add_webhook(body: WebhookCreate, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    _admin(principal)
    webhook_limiter.check(principal.user_id)
    try:
        await alerts.check(body.url, body.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    existing = [h for h in await db.list_webhooks(principal.org_id) if not h.get("revoked_at")]
    if len(existing) >= MAX_WEBHOOKS:
        raise HTTPException(status_code=409, detail=f"At most {MAX_WEBHOOKS} webhooks. Remove one first.")
    doc: dict[str, Any] = {"url": body.url, "kind": body.kind, "include_suspect": body.include_suspect, "on_forks": body.on_forks, "created_by": principal.user_id}
    secret = None
    if body.kind == "generic":  # signs each post, so the receiver can tell it came from us. Shown once.
        secret = secrets.token_urlsafe(24)
        doc["secret"] = secret
    hook_id = await db.create_webhook(principal.org_id, doc)
    await audit.record(principal.org_id, principal.user_id, "webhook.create", hook_id, {"kind": body.kind, "include_suspect": body.include_suspect})
    return {**_shown({**doc, "id": hook_id}), **({"secret": secret} if secret else {})}


@router.get("/webhooks")
async def list_webhooks(principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    _admin(principal)
    return [_shown(h) for h in await db.list_webhooks(principal.org_id)]


@router.delete("/webhooks/{webhook_id}")
async def remove_webhook(webhook_id: str, principal: Principal = Depends(get_principal)) -> dict[str, str]:
    _admin(principal)
    if not await db.revoke_webhook(principal.org_id, webhook_id):
        raise HTTPException(status_code=404, detail="Webhook not found or already removed")
    await audit.record(principal.org_id, principal.user_id, "webhook.remove", webhook_id)
    return {"id": webhook_id}


@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: str, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """Send a sample alert, so you can see it arrive."""
    _admin(principal)
    webhook_limiter.check(principal.user_id)
    hook = next((h for h in await db.list_webhooks(principal.org_id) if h["id"] == webhook_id and not h.get("revoked_at")), None)
    if hook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    sample = alerts.event_for(
        {"id": "sample", "workflow": "A sample alert", "outcome": "fail", "started_at": None,
         "oracle_detail": {"verdict": {"name": "your_check", "reason": "This is a test message from AgentTrace."}}}, None, None,
    )
    status = await alerts.deliver(hook, alerts.slack_message(sample) if hook["kind"] == "slack" else sample)
    return {"delivered": status is not None and 200 <= status < 300, "status": status}
