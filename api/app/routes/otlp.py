"""OpenTelemetry traces in, as OTLP over HTTP with JSON. Authenticated by the workspace's ingest key, which
an exporter sends as `Authorization: Bearer at_live_...` (OTEL_EXPORTER_OTLP_HEADERS). The workspace comes
from the key, never from the body. JSON only: a collector's otlphttp exporter can send it with `encoding: json`;
protobuf needs a decoder this API does not have yet, so it is refused with that explanation."""

import json
import zlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app import db
from app.auth import ingest_workspace
from app.importer import import_run
from app.otlp import traces_to_runs

router = APIRouter(prefix="/v1")

MAX_BODY = 5 * 1024 * 1024  # decoded, so a small compressed body cannot expand past it
MAX_TRACES = 50  # per request


def _inflate(body: bytes) -> bytes:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = d.decompress(body, MAX_BODY + 1)
    except zlib.error:
        raise HTTPException(status_code=400, detail="The body is not valid gzip") from None
    if len(out) > MAX_BODY or d.unconsumed_tail:
        raise HTTPException(status_code=413, detail="The request is too large")
    return out


@router.post("/traces")
async def otlp_traces(request: Request, workspace: str = Depends(ingest_workspace)) -> dict[str, Any]:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(
            status_code=415,
            detail="AgentTrace reads OTLP as JSON only. Set OTEL_EXPORTER_OTLP_PROTOCOL=http/json, or use an "
                   "OpenTelemetry Collector otlphttp exporter with `encoding: json`.",
        )
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY:  # refuse before reading it
        raise HTTPException(status_code=413, detail="The request is too large")
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(status_code=413, detail="The request is too large")
    if request.headers.get("content-encoding", "").lower() == "gzip":
        body = _inflate(body)
    try:
        runs, rejected, reason = traces_to_runs(json.loads(body))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="This is not OTLP trace JSON") from None
    if len(runs) > MAX_TRACES:
        rejected += sum(len(r.steps) for _, r in runs[MAX_TRACES:])
        reason = reason or f"more than {MAX_TRACES} traces in one request"
        runs = runs[:MAX_TRACES]
    for trace_id, run in runs:
        try:
            await import_run(workspace, run, run_id=trace_id)
        except db.RunConflict:  # a trace id is a run id, and another workspace already holds this one
            rejected += len(run.steps)
            reason = reason or "this trace id is already used by another workspace"
    if rejected:
        return {"partialSuccess": {"rejectedSpans": rejected, "errorMessage": reason}}
    return {}
