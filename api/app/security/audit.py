"""Who did what, and when. One audit record per sensitive action: launching an experiment,
running a root-cause analysis, deleting a run. Scoped to the workspace; admins can read it."""

import logging
from datetime import UTC, datetime
from typing import Any

from app import db

log = logging.getLogger(__name__)


async def record(
    workspace: str, actor: str, action: str, target: str, detail: dict[str, Any] | None = None,
    *, strict: bool = False,
) -> None:
    """Write an audit record. `strict=True` lets a failure propagate, for actions that must not
    happen unrecorded (deleting data). Otherwise a failed write is logged and the action goes on."""
    doc = {"workspace": workspace, "actor": actor, "action": action, "target": target,
           "detail": detail or {}, "at": datetime.now(UTC).isoformat()}
    try:
        await db.create_audit(workspace, doc)
    except Exception as exc:
        if strict:
            raise
        log.warning("audit write failed for %s: %s", action, type(exc).__name__)
