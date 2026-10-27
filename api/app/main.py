import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import get_settings
from app.routes import agent, audit, experiments, imports, ingest, keys, otlp, public, rca, runs, sample, webhooks, worker
from app.security.limits import MAX_BODY_BYTES

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Keep database connections between requests while the API runs (see db.enable_pool)."""
    db.enable_pool()
    try:
        yield
    finally:
        await db.close_pool()


# In production the interactive API docs are off: nothing needs them there.
_prod = settings.env == "prod"
app = FastAPI(
    lifespan=lifespan, title="AgentTrace API", version="0.0.1",
    docs_url=None if _prod else "/docs", redoc_url=None if _prod else "/redoc",
    openapi_url=None if _prod else "/openapi.json",
)

# Bearer tokens travel in the Authorization header, not cookies, so no credentialed CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.web_origins,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(ingest.router)
app.include_router(imports.router)
app.include_router(otlp.router)
app.include_router(worker.router)
app.include_router(agent.router)
app.include_router(webhooks.router)
app.include_router(keys.router)
app.include_router(sample.router)
app.include_router(runs.router)
app.include_router(experiments.router)
app.include_router(rca.router)
app.include_router(public.router)
app.include_router(audit.router)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Refuse oversized bodies early. Covers requests that declare a Content-Length; a hostile
    client that streams without one is a gap a reverse proxy limit would close (see SECURITY.md)."""
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request body too large"}, status_code=413)
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, bool]:
    # The key's presence only: a paid call on every health check would be wasteful.
    return {"ok": True, "db": await db.ping(), "anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())}
