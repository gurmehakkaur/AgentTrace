"""SurrealDB connection plus the data-access helpers (runs, steps, forks, api keys).

Every function that touches run data takes `workspace` and filters on it. Callers get the
workspace from the verified key or token, never from a request body. Each call opens its own
connection; that is simple, and fast enough for the volumes here.
"""

import asyncio
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from surrealdb import AlreadyExistsError, AsyncSurreal, RecordID

from app.models import Step

from app.config import DB_CONNECT_TIMEOUT_S, Settings, get_settings

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema.surql"


class RunConflict(Exception):
    """A run id that already exists in a different workspace."""


def _signin_vars(s: Settings) -> dict[str, str]:
    """Credentials payload for the level the user was created at (SDK: signin docstring)."""
    creds = {"username": s.surreal_user, "password": s.surreal_pass}
    if s.surreal_auth_level == "namespace":
        creds["namespace"] = s.surreal_ns
    elif s.surreal_auth_level == "database":
        creds["namespace"] = s.surreal_ns
        creds["database"] = s.surreal_db
    return creds


_shared: ContextVar[Any] = ContextVar("surreal_shared", default=None)


@asynccontextmanager
async def session() -> AsyncIterator[None]:
    """Share ONE connection between the calls made inside this block. Opening a connection to SurrealDB Cloud
    costs about a second (TLS, sign-in), and a worker job makes dozens of calls: without this one took 21 s.
    Everything inside runs one after another, in this task, so one connection is safe."""
    if _shared.get() is not None:
        yield
        return
    async with connect() as c:
        token = _shared.set(c)
        try:
            yield
        finally:
            _shared.reset(token)


# --- connections -----------------------------------------------------------------------------
# Opening a connection to SurrealDB Cloud takes about 0.4 s and CLOSING one takes about 1 s, while a query takes
# 0.06 s. A request that opened and closed its own connection spent over 90% of its time on that. So inside the
# running API a few idle connections are kept and handed to one caller at a time (never shared by two at once).
# A connection that raised is thrown away, not reused. One idle for a while is checked with a tiny query first.
# Scripts and tests do not switch this on, and SURREAL_POOL=0 switches it off in the API.
_pool: list[tuple[Any, float]] | None = None  # None: off. Otherwise the idle connections and when each was last used.
MAX_IDLE = 4
CHECK_AFTER_S = 15.0
_closing: set[asyncio.Task] = set()


def enable_pool() -> None:
    global _pool
    if os.environ.get("SURREAL_POOL", "1") != "0" and _pool is None:
        _pool = []


async def close_pool() -> None:
    global _pool
    idle, _pool = _pool or [], None
    await asyncio.gather(*(_quiet_close(c) for c, _ in idle), return_exceptions=True)
    await asyncio.gather(*list(_closing), return_exceptions=True)


async def _quiet_close(conn: Any) -> None:
    try:
        await conn.close()
    except Exception as exc:
        log.warning("closing a connection failed: %s", type(exc).__name__)


def _drop(conn: Any) -> None:
    """Close in the background: the caller must not wait the second a close takes."""
    task = asyncio.ensure_future(_quiet_close(conn))
    _closing.add(task)
    task.add_done_callback(_closing.discard)


async def _open_once(s: Settings) -> Any:
    conn = AsyncSurreal(s.surreal_url)
    await conn.connect()
    try:
        if s.surreal_token:
            await conn.authenticate(s.surreal_token)
        else:
            await conn.signin(_signin_vars(s))
        await conn.use(s.surreal_ns, s.surreal_db)
    except BaseException:
        await _quiet_close(conn)
        raise
    return conn


async def _open(s: Settings) -> Any:
    """Open one, and once more if the first try timed out or the network dropped it: the handshake to SurrealDB
    Cloud now and then takes longer than its limit, and one slow handshake should not fail a whole request."""
    try:
        return await _open_once(s)
    except (TimeoutError, OSError, ConnectionError) as exc:
        log.warning("opening a database connection failed (%s); trying once more", type(exc).__name__)
        return await _open_once(s)


async def _take(s: Settings) -> Any:
    while _pool:
        conn, last_used = _pool.pop()
        if time.monotonic() - last_used > CHECK_AFTER_S:
            try:
                await asyncio.wait_for(conn.query("RETURN 1;"), timeout=3)
            except BaseException as exc:  # gone stale while idle
                _drop(conn)
                if not isinstance(exc, Exception):
                    raise
                continue
        return conn
    return await _open(s)


def _give(conn: Any) -> None:
    if _pool is not None and len(_pool) < MAX_IDLE:
        _pool.append((conn, time.monotonic()))
    else:
        _drop(conn)


_shared: ContextVar[Any] = ContextVar("surreal_shared", default=None)


@asynccontextmanager
async def session() -> AsyncIterator[None]:
    """Hold ONE connection for the calls made inside this block. Everything inside runs one after another in this
    task, so one connection is safe. Never start a background task inside it: the task would inherit the connection
    and outlive it."""
    if _shared.get() is not None:
        yield
        return
    async with connect() as c:
        token = _shared.set(c)
        try:
            yield
        finally:
            _shared.reset(token)


@asynccontextmanager
async def connect(settings: Settings | None = None) -> AsyncIterator[AsyncSurreal]:
    """An authenticated connection scoped to SURREAL_NS / SURREAL_DB: the one a `session()` holds, an idle one from
    the pool, or a new one that is closed when the block ends.

    The SDK appends /rpc to the url itself, so SURREAL_URL is the bare host.
    """
    shared = _shared.get()
    if shared is not None and settings is None:
        yield shared
        return
    s = settings or get_settings()
    if _pool is not None and settings is None:
        conn = await _take(s)
        try:
            yield conn
        except BaseException:
            _drop(conn)  # it may be half way through something: never hand it to anyone else
            raise
        _give(conn)
        return
    async with AsyncSurreal(s.surreal_url) as db:
        if s.surreal_token:
            await db.authenticate(s.surreal_token)
        else:
            await db.signin(_signin_vars(s))
        await db.use(s.surreal_ns, s.surreal_db)
        yield db


async def ping(timeout: float = DB_CONNECT_TIMEOUT_S) -> bool:
    """True if we can connect, authenticate and run a query within `timeout` seconds.

    Never raises and never logs exception text (it could echo credentials or hosts).
    """
    s = get_settings()
    if not s.surreal_configured:
        return False

    async def _probe() -> bool:
        async with connect() as db:
            await db.query("RETURN 1;")
        return True

    try:
        return await asyncio.wait_for(_probe(), timeout=timeout)
    except Exception as exc:  # includes TimeoutError
        log.warning("surreal ping failed: %s", type(exc).__name__)
        return False


# --- helpers -------------------------------------------------------------------------------

def _plain(value: Any) -> Any:
    """RecordIDs (not JSON-serialisable) become "table:key" strings, recursively."""
    if isinstance(value, RecordID):
        return f"{value.table_name}:{value.id}"
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _row(record: dict[str, Any]) -> dict[str, Any]:
    """A result row as plain JSON, with `id` reduced to the key part (run id, not "run:...")."""
    out = _plain({k: v for k, v in record.items() if k != "id"})
    out["id"] = record["id"].id
    return out


def _now() -> str:
    return datetime.now(UTC).isoformat()


# --- schema and workspaces -------------------------------------------------------------------

async def apply_schema() -> None:
    """Run schema.surql statement by statement. Idempotent (DEFINE ... OVERWRITE)."""
    text = "\n".join(l for l in SCHEMA_PATH.read_text().splitlines() if not l.strip().startswith("--"))
    async with connect() as c:
        for statement in (s.strip() for s in text.split(";")):
            if statement:
                await c.query(statement + ";")


async def upsert_workspace(workspace: str, name: str) -> None:
    async with connect() as c:
        await c.query(
            "UPSERT type::record('workspace', $id) MERGE $d",
            {"id": workspace, "d": {"name": name, "retention_days": 14, "created_at": _now()}},
        )


async def create_api_key(
    workspace: str, prefix: str, sha256: str, created_by: str, scopes: tuple[str, ...] = ("ingest",)
) -> None:
    async with connect() as c:
        await c.query(
            "CREATE api_key CONTENT $d",
            {"d": {"workspace": workspace, "prefix": prefix, "sha256": sha256, "created_by": created_by,
                   "scopes": list(scopes), "created_at": _now()}},
        )


async def list_api_keys(workspace: str) -> list[dict[str, Any]]:
    """A workspace's ingest keys, newest first. Only the display prefix is ever stored or returned."""
    async with connect() as c:
        rows = await c.query(
            "SELECT id, prefix, scopes, created_by, created_at, last_seen_at, revoked_at FROM api_key WHERE workspace = $ws "
            "ORDER BY created_at DESC", {"ws": workspace},
        )
    return [{**_row(r), "scopes": r.get("scopes") or ["ingest"]} for r in rows]  # a key from before scopes could only send runs


async def touch_key(key_id: str) -> None:
    """Note that a key was just used, so the app can say whether a worker is connected."""
    async with connect() as c:
        await c.query("UPDATE type::record('api_key', $id) SET last_seen_at = $now", {"id": key_id, "now": _now()})


async def count_workers_since(workspace: str, since_iso: str) -> int:
    """How many worker keys of the workspace have asked for a job since `since_iso`."""
    async with connect() as c:
        rows = await c.query(
            "SELECT count() AS n FROM api_key WHERE workspace = $ws AND scopes CONTAINS 'worker' AND revoked_at = NONE "
            "AND last_seen_at > $since GROUP ALL",
            {"ws": workspace, "since": since_iso},
        )
    return int(rows[0]["n"]) if rows else 0


async def revoke_api_key(workspace: str, key_id: str) -> bool:
    async with connect() as c:
        rows = await c.query(
            "UPDATE type::record('api_key', $id) SET revoked_at = $now WHERE workspace = $ws AND revoked_at = NONE RETURN AFTER",
            {"id": key_id, "ws": workspace, "now": _now()},
        )
    return bool(rows)


async def key_for_hash(sha256: str) -> dict[str, Any] | None:
    """A non-revoked key's id, workspace and scopes, or None. A key made before scopes existed can only ingest."""
    async with connect() as c:
        rows = await c.query(
            "SELECT id, workspace, scopes FROM api_key WHERE sha256 = $h AND revoked_at = NONE", {"h": sha256}
        )
    if not rows:
        return None
    return {"id": _row(rows[0])["id"], "workspace": rows[0]["workspace"], "scopes": rows[0].get("scopes") or ["ingest"]}


# --- alert webhooks ---------------------------------------------------------------------------

async def create_webhook(workspace: str, doc: dict[str, Any]) -> str:
    """Store a webhook. Its address is a secret (a Slack address lets anyone post), so it is only ever read
    back by the sender and shown to people as a host and the last few characters."""
    async with connect() as c:
        rows = await c.query("CREATE webhook CONTENT $d", {"d": {**doc, "workspace": workspace, "created_at": _now()}})
    return _row(rows[0])["id"]


async def list_webhooks(workspace: str) -> list[dict[str, Any]]:
    async with connect() as c:
        rows = await c.query("SELECT * FROM webhook WHERE workspace = $ws ORDER BY created_at DESC", {"ws": workspace})
    return [_row(r) for r in rows]


async def revoke_webhook(workspace: str, webhook_id: str) -> bool:
    async with connect() as c:
        rows = await c.query(
            "UPDATE type::record('webhook', $id) SET revoked_at = $now WHERE workspace = $ws AND revoked_at = NONE RETURN AFTER",
            {"id": webhook_id, "ws": workspace, "now": _now()},
        )
    return bool(rows)


async def claim_alert(workspace: str, run_id: str) -> bool:
    """True the first time it is called for a run, so a retried finish does not alert twice."""
    async with connect() as c:
        rows = await c.query(
            "UPDATE type::record('run', $id) SET alerted_at = $now WHERE workspace = $ws AND alerted_at = NONE RETURN AFTER",
            {"id": run_id, "ws": workspace, "now": _now()},
        )
    return bool(rows)


# --- runs and steps --------------------------------------------------------------------------

async def create_run(
    workspace: str, run_id: str, workflow: str, started_at: str, kind: str = "recorded"
) -> bool:
    """True if created, False if it already existed in this workspace (retry-safe)."""
    doc = {"workspace": workspace, "workflow": workflow, "kind": kind,
           "status": "running", "started_at": started_at}
    async with connect() as c:
        try:
            await c.query("CREATE type::record('run', $id) CONTENT $d", {"id": run_id, "d": doc})
            return True
        except AlreadyExistsError:
            rows = await c.query("SELECT workspace FROM type::record('run', $id)", {"id": run_id})
            if rows and rows[0]["workspace"] == workspace:
                return False
            raise RunConflict(run_id) from None


async def run_exists(workspace: str, run_id: str) -> bool:
    async with connect() as c:
        rows = await c.query(
            "SELECT id FROM type::record('run', $id) WHERE workspace = $ws", {"id": run_id, "ws": workspace}
        )
    return bool(rows)


async def add_steps(workspace: str, run_id: str, steps: list[dict[str, Any]]) -> int:
    """Insert steps, skipping any (run, idx) already stored. Returns how many were new.

    Idempotent: a step's record id is "<run>_<idx>", so a retried batch hits AlreadyExistsError
    and adds neither a duplicate step nor duplicate edges. The caller has checked that the run
    belongs to `workspace`.
    """
    added = 0
    async with connect() as c:
        for step in steps:
            key = f"{run_id}_{step['idx']}"
            try:
                await c.query("CREATE type::record('step', $k) CONTENT $s", {"k": key, "s": step})
            except AlreadyExistsError:
                continue
            await c.query(
                "RELATE (type::record('run', $r))->has_step->(type::record('step', $k))",
                {"r": run_id, "k": key},
            )
            if step["idx"] > 1:
                await c.query(
                    "RELATE (type::record('step', $p))->next->(type::record('step', $k))",
                    {"p": f"{run_id}_{step['idx'] - 1}", "k": key},
                )
            added += 1
    return added


async def finish_run(
    workspace: str, run_id: str, status: str, outcome: str | None, oracle_detail: dict | None
) -> bool:
    """Close a run: status, outcome, oracle detail, end time and token totals."""
    async with connect() as c:
        totals = await c.query(
            "SELECT math::sum(tokens_in) AS i, math::sum(tokens_out) AS o FROM step WHERE run = $r GROUP ALL",
            {"r": run_id},
        )
        merge = {"status": status, "ended_at": _now(),
                 "tokens_in": totals[0]["i"] if totals else 0,
                 "tokens_out": totals[0]["o"] if totals else 0}
        if outcome is not None:
            merge["outcome"] = outcome
        if oracle_detail is not None:
            merge["oracle_detail"] = oracle_detail
        updated = await c.query(
            "UPDATE type::record('run', $id) MERGE $m WHERE workspace = $ws",
            {"id": run_id, "m": merge, "ws": workspace},
        )
    return bool(updated)


async def get_run_with_steps(workspace: str, run_id: str) -> dict[str, Any] | None:
    """The run plus its steps in order, reached by graph traversal (run->has_step->step)."""
    async with connect() as c:
        rows = await c.query(
            "SELECT *, ->has_step->step.* AS steps FROM type::record('run', $id) WHERE workspace = $ws",
            {"id": run_id, "ws": workspace},
        )
    if not rows:
        return None
    steps = sorted(rows[0].pop("steps"), key=lambda s: s["idx"])
    run = _row(rows[0])
    # SurrealDB drops fields stored as None; validating through Step puts them back as None.
    run["steps"] = [Step.model_validate(_row(s)).model_dump() for s in steps]
    return run


async def list_runs(workspace: str, limit: int = 50, kind: str | None = None) -> list[dict[str, Any]]:
    """Newest first. `kind="recorded"` leaves out the runs a fork makes (one per attempt): without it
    a few forks fill the list and push the runs people recorded out of it."""
    where = "workspace = $ws" + (" AND kind = $kind" if kind else "")
    async with connect() as c:
        rows = await c.query(
            f"SELECT * FROM run WHERE {where} ORDER BY started_at DESC LIMIT $n",
            {"ws": workspace, "n": limit, **({"kind": kind} if kind else {})},
        )
    return [_row(r) for r in rows]


# --- forks -----------------------------------------------------------------------------------

async def create_fork_edge(
    workspace: str, fork_run_id: str, parent_run_id: str, at_idx: int, arm: str,
    experiment: str | None = None,
) -> None:
    """fork_run -forked_from-> parent. Both runs must belong to `workspace`."""
    if not (await run_exists(workspace, fork_run_id) and await run_exists(workspace, parent_run_id)):
        raise LookupError("both runs must exist in the workspace")
    async with connect() as c:
        await c.query(
            "RELATE (type::record('run', $f))->forked_from->(type::record('run', $p)) CONTENT $d",
            {"f": fork_run_id, "p": parent_run_id,
             "d": {"at_idx": at_idx, "arm": arm, "experiment": experiment}},
        )


async def list_forks(workspace: str, parent_run_id: str) -> list[dict[str, Any]]:
    async with connect() as c:
        rows = await c.query(
            "SELECT in AS fork_run, at_idx, arm, experiment FROM forked_from "
            "WHERE out = type::record('run', $p) AND in.workspace = $ws",
            {"p": parent_run_id, "ws": workspace},
        )
    return [{**_plain(r), "fork_run": r["fork_run"].id} for r in rows]


# --- experiments -----------------------------------------------------------------------------

async def create_experiment(workspace: str, experiment_id: str, doc: dict[str, Any]) -> None:
    async with connect() as c:
        await c.query(
            "CREATE type::record('experiment', $id) CONTENT $d",
            {"id": experiment_id, "d": {**doc, "workspace": workspace}},
        )


async def update_experiment(workspace: str, experiment_id: str, merge: dict[str, Any]) -> None:
    async with connect() as c:
        await c.query(
            "UPDATE type::record('experiment', $id) MERGE $m WHERE workspace = $ws",
            {"id": experiment_id, "m": merge, "ws": workspace},
        )


async def update_experiment_if_rev(workspace: str, experiment_id: str, rev: int, merge: dict[str, Any]) -> bool:
    """Merge into an experiment only if nobody changed it since `rev` was read: two workers claiming at once
    cannot both take the same tile. The merge must set the next rev. True if it applied."""
    async with connect() as c:
        rows = await c.query(
            "UPDATE type::record('experiment', $id) MERGE $m WHERE workspace = $ws AND (rev ?? 0) = $rev RETURN AFTER",
            {"id": experiment_id, "m": merge, "ws": workspace, "rev": rev},
        )
    return bool(rows)


async def get_experiment(workspace: str, experiment_id: str) -> dict[str, Any] | None:
    async with connect() as c:
        rows = await c.query(
            "SELECT * FROM type::record('experiment', $id) WHERE workspace = $ws",
            {"id": experiment_id, "ws": workspace},
        )
    return _row(rows[0]) if rows else None


async def create_tested_edge(experiment_id: str, run_id: str) -> None:
    async with connect() as c:
        await c.query(
            "RELATE (type::record('experiment', $e))->tested->(type::record('run', $r))",
            {"e": experiment_id, "r": run_id},
        )


async def get_run_summary(workspace: str, run_id: str) -> dict[str, Any] | None:
    """Just the outcome and token totals of a run (no steps)."""
    async with connect() as c:
        rows = await c.query(
            "SELECT status, outcome, tokens_in, tokens_out FROM type::record('run', $id) WHERE workspace = $ws",
            {"id": run_id, "ws": workspace},
        )
    return _plain(rows[0]) if rows else None


async def list_memory_scopes(workspace: str, limit: int = 50) -> list[str]:
    """Agent Memory scopes (one per source run) that hold this workspace's remembered patterns,
    newest first. Recall needs the exact list: a parent scope does not include its children."""
    async with connect() as c:
        rows = await c.query(
            "SELECT memory_scope, finished_at FROM experiment "
            "WHERE workspace = $ws AND remembered = true ORDER BY finished_at DESC LIMIT $n",
            {"ws": workspace, "n": limit},
        )
    return list(dict.fromkeys(r["memory_scope"] for r in rows if r.get("memory_scope")))


# --- benchmarks ------------------------------------------------------------------------------

async def create_benchmark(workspace: str, benchmark_id: str, doc: dict[str, Any]) -> None:
    async with connect() as c:
        await c.query(
            "CREATE type::record('benchmark', $id) CONTENT $d", {"id": benchmark_id, "d": {**doc, "workspace": workspace}}
        )


async def get_benchmark_for_experiment(workspace: str, experiment_id: str) -> dict[str, Any] | None:
    """The newest benchmark attached to an experiment."""
    async with connect() as c:
        rows = await c.query(
            "SELECT * FROM benchmark WHERE workspace = $ws AND experiment = $e ORDER BY created_at DESC LIMIT 1",
            {"ws": workspace, "e": experiment_id},
        )
    return _row(rows[0]) if rows else None


# --- RCA reports -----------------------------------------------------------------------------

async def create_rca_report(workspace: str, report_id: str, doc: dict[str, Any]) -> None:
    async with connect() as c:
        await c.query(
            "CREATE type::record('rca_report', $id) CONTENT $d",
            {"id": report_id, "d": {**doc, "workspace": workspace}},
        )


async def update_rca_report(workspace: str, report_id: str, merge: dict[str, Any]) -> None:
    async with connect() as c:
        await c.query(
            "UPDATE type::record('rca_report', $id) MERGE $m WHERE workspace = $ws",
            {"id": report_id, "m": merge, "ws": workspace},
        )


async def get_latest_rca_report(workspace: str, run_id: str) -> dict[str, Any] | None:
    async with connect() as c:
        rows = await c.query(
            "SELECT * FROM rca_report WHERE workspace = $ws AND run = $r ORDER BY created_at DESC LIMIT 1",
            {"ws": workspace, "r": run_id},
        )
    return _row(rows[0]) if rows else None


# --- featured demo content --------------------------------------------------------------------

async def clear_featured(workspace: str) -> None:
    """Un-feature everything in a workspace, so a re-seed leaves exactly one featured set."""
    async with connect() as c:
        await c.query("UPDATE run SET featured = false WHERE workspace = $ws AND featured = true", {"ws": workspace})
        await c.query("UPDATE experiment SET featured = false WHERE workspace = $ws AND featured = true", {"ws": workspace})


async def set_run_featured(workspace: str, run_id: str) -> None:
    async with connect() as c:
        await c.query(
            "UPDATE type::record('run', $id) SET featured = true WHERE workspace = $ws", {"id": run_id, "ws": workspace}
        )


async def get_featured_run_id(workspace: str) -> str | None:
    async with connect() as c:
        rows = await c.query(
            "SELECT id FROM run WHERE workspace = $ws AND featured = true ORDER BY started_at DESC LIMIT 1",
            {"ws": workspace},
        )
    return rows[0]["id"].id if rows else None


async def list_featured_experiments(workspace: str) -> list[dict[str, Any]]:
    async with connect() as c:
        rows = await c.query(
            "SELECT * FROM experiment WHERE workspace = $ws AND featured = true", {"ws": workspace}
        )
    return [_row(r) for r in rows]


async def list_experiments(workspace: str, limit: int = 200) -> list[dict[str, Any]]:
    """Every experiment in the workspace, oldest first: the forks on the project timeline."""
    async with connect() as c:
        rows = await c.query(
            "SELECT * FROM experiment WHERE workspace = $ws ORDER BY created_at ASC LIMIT $n",
            {"ws": workspace, "n": limit},
        )
    return [_row(r) for r in rows]


async def agents_for_runs(run_ids: list[str]) -> dict[str, dict[int, str]]:
    """Which agent ran as each agent turn of these runs: {run: {node_run_idx: agent}}. For labels only."""
    if not run_ids:
        return {}
    async with connect() as c:
        rows = await c.query("SELECT run, node_run_idx, agent FROM step WHERE run IN $ids", {"ids": run_ids})
    out: dict[str, dict[int, str]] = {}
    for r in rows:
        out.setdefault(r["run"], {})[r["node_run_idx"]] = r["agent"]
    return out


async def list_experiments_for_runs(workspace: str, run_ids: list[str]) -> list[dict[str, Any]]:
    """Experiments started from any of these runs, oldest first."""
    if not run_ids:
        return []
    async with connect() as c:
        rows = await c.query(
            "SELECT * FROM experiment WHERE workspace = $ws AND parent_run IN $ids ORDER BY created_at ASC",
            {"ws": workspace, "ids": run_ids},
        )
    return [_row(r) for r in rows]


async def list_experiments_for_run(workspace: str, run_id: str) -> list[dict[str, Any]]:
    """Every experiment (fork) started from this run, oldest first: the branches of its graph."""
    async with connect() as c:
        rows = await c.query(
            "SELECT * FROM experiment WHERE workspace = $ws AND parent_run = $r ORDER BY created_at ASC",
            {"ws": workspace, "r": run_id},
        )
    return [_row(r) for r in rows]


# --- audit, caps ------------------------------------------------------------------------------

async def create_audit(workspace: str, doc: dict[str, Any]) -> None:
    async with connect() as c:
        await c.query("CREATE audit CONTENT $d", {"d": {**doc, "workspace": workspace}})


async def list_audit(workspace: str, limit: int = 100) -> list[dict[str, Any]]:
    async with connect() as c:
        rows = await c.query(
            "SELECT * FROM audit WHERE workspace = $ws ORDER BY at DESC LIMIT $n", {"ws": workspace, "n": limit}
        )
    return [_row(r) for r in rows]


async def count_experiments_since(created_by: str, since_iso: str) -> int:
    """Experiments a user started at or after `since_iso` (ISO strings sort chronologically)."""
    async with connect() as c:
        rows = await c.query(
            "SELECT count() AS n FROM experiment WHERE created_by = $u AND created_at >= $since GROUP ALL",
            {"u": created_by, "since": since_iso},
        )
    return rows[0]["n"] if rows else 0


# --- deleting a run and everything derived from it -------------------------------------------

async def _delete_runs(c: Any, workspace: str, run_ids: list[str]) -> dict[str, Any]:
    """Delete these runs and what hangs off them: steps and their edges, experiments run on them,
    those experiments' tested edges, and root-cause reports. Returns counts and the Agent Memory
    scopes the experiments had written to (the caller forgets those)."""
    run_rids = [RecordID("run", r) for r in run_ids]
    exps = await c.query(
        "SELECT id, memory_scope FROM experiment WHERE workspace = $ws AND parent_run IN $ids",
        {"ws": workspace, "ids": run_ids},
    )
    exp_rids = [e["id"] for e in exps]
    count = lambda rows: rows[0]["n"] if rows else 0  # noqa: E731
    steps = count(await c.query("SELECT count() AS n FROM step WHERE run IN $ids GROUP ALL", {"ids": run_ids}))
    reports = count(await c.query(
        "SELECT count() AS n FROM rca_report WHERE workspace = $ws AND run IN $ids GROUP ALL", {"ws": workspace, "ids": run_ids}
    ))

    await c.query("DELETE benchmark WHERE workspace = $ws AND experiment IN $e", {"ws": workspace, "e": [r.id for r in exp_rids]})
    await c.query("DELETE tested WHERE in IN $e OR out IN $r", {"e": exp_rids, "r": run_rids})
    await c.query("DELETE experiment WHERE workspace = $ws AND parent_run IN $ids", {"ws": workspace, "ids": run_ids})
    await c.query("DELETE rca_report WHERE workspace = $ws AND run IN $ids", {"ws": workspace, "ids": run_ids})
    for run_id, rid in zip(run_ids, run_rids, strict=True):
        await c.query("DELETE next WHERE in.run = $r", {"r": run_id})
        await c.query("DELETE has_step WHERE in = $rid", {"rid": rid})
        await c.query("DELETE forked_from WHERE in = $rid OR out = $rid", {"rid": rid})
        await c.query("DELETE step WHERE run = $r", {"r": run_id})
        await c.query("DELETE $rid", {"rid": rid})
    return {
        "runs": len(run_ids), "steps": steps, "experiments": len(exps), "rca_reports": reports,
        "run_ids": run_ids, "memory_scopes": sorted({e["memory_scope"] for e in exps if e.get("memory_scope")}),
    }


async def delete_run_cascade(workspace: str, run_id: str) -> dict[str, Any] | None:
    """Delete a run in `workspace` together with every fork of it (and forks of forks) and all
    derived data. None if the run is not in the workspace."""
    async with connect() as c:
        found = await c.query(
            "SELECT id FROM type::record('run', $id) WHERE workspace = $ws", {"id": run_id, "ws": workspace}
        )
        if not found:
            return None
        ids, frontier = [run_id], [run_id]
        while frontier:  # walk down the fork tree
            rows = await c.query(
                "SELECT in AS fork FROM forked_from WHERE out IN $outs AND in.workspace = $ws",
                {"outs": [RecordID("run", r) for r in frontier], "ws": workspace},
            )
            frontier = [r["fork"].id for r in rows if r["fork"].id not in ids]
            ids += frontier
        return await _delete_runs(c, workspace, ids)


# --- test / smoke cleanup --------------------------------------------------------------------

async def purge_workspace(workspace: str) -> None:
    """Delete everything stored under `workspace`. For tests and smoke scripts that use a
    throwaway workspace id; never called by the API."""
    if not re.match(r"^(test|smoke)-", workspace):
        raise ValueError("purge_workspace only deletes throwaway test-* / smoke-* workspaces")
    async with connect() as c:
        runs = await c.query("SELECT VALUE id FROM run WHERE workspace = $ws", {"ws": workspace})
        if runs:
            await _delete_runs(c, workspace, [r.id for r in runs])
        await c.query("DELETE experiment WHERE workspace = $ws", {"ws": workspace})
        await c.query("DELETE rca_report WHERE workspace = $ws", {"ws": workspace})
        await c.query("DELETE audit WHERE workspace = $ws", {"ws": workspace})
        await c.query("DELETE benchmark WHERE workspace = $ws", {"ws": workspace})
        await c.query("DELETE api_key WHERE workspace = $ws", {"ws": workspace})
        await c.query("DELETE webhook WHERE workspace = $ws", {"ws": workspace})
        await c.query("DELETE type::record('workspace', $ws)", {"ws": workspace})
