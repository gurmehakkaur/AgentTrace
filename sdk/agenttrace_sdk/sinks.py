"""Where recorded runs go. The recorder only talks to this interface.

Records are plain dicts so any sink can serialise them.
"""

import asyncio
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any, Protocol


class Sink(Protocol):
    async def start_run(self, run: dict[str, Any]) -> None: ...

    async def add_steps(self, run_id: str, steps: list[dict[str, Any]]) -> None:
        """Called once per node run. Receivers must be idempotent on (run_id, idx)."""
        ...

    async def finish_run(
        self, run_id: str, status: str, outcome: str | None = None,
        oracle_detail: dict[str, Any] | None = None,
    ) -> None: ...


class ListSink:
    """In-memory sink for tests and local debugging."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.steps: list[dict[str, Any]] = []

    async def start_run(self, run: dict[str, Any]) -> None:
        self.runs[run["id"]] = dict(run)

    async def add_steps(self, run_id: str, steps: list[dict[str, Any]]) -> None:
        self.steps.extend(steps)

    async def finish_run(
        self, run_id: str, status: str, outcome: str | None = None,
        oracle_detail: dict[str, Any] | None = None,
    ) -> None:
        self.runs[run_id].update(
            status=status, outcome=outcome, oracle_detail=oracle_detail,
            ended_at=datetime.now(UTC).isoformat(),
        )

    def steps_for(self, run_id: str) -> list[dict[str, Any]]:
        return sorted((s for s in self.steps if s["run"] == run_id), key=lambda s: s["idx"])


class HttpSinkError(RuntimeError):
    pass


class HttpSink:
    """POSTs runs and step batches to an AgentTrace API (POST /v1/runs, .../steps, .../finish).

    Stdlib only (urllib in a worker thread), so the SDK keeps zero dependencies. Retries
    connection errors and 5xx; the API is idempotent per (run, idx), so a retry is safe.
    The API key is sent as a Bearer token and never appears in error messages.
    """

    def __init__(self, base_url: str, api_key: str, *, retries: int = 2, timeout: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._retries = retries
        self._timeout = timeout  # generous: a free-tier API can take ~a minute to wake

    def _post_sync(self, path: str, payload: dict[str, Any]) -> None:
        request = urllib.request.Request(
            self._base + path,
            data=json.dumps(payload, default=str).encode(),
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(self._retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self._timeout):
                    return
            except urllib.error.HTTPError as exc:
                if exc.code < 500 or attempt == self._retries:
                    detail = exc.read()[:200].decode(errors="replace")
                    raise HttpSinkError(f"POST {path} -> {exc.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == self._retries:
                    raise HttpSinkError(f"POST {path} failed: {type(exc).__name__}") from None
            time.sleep(0.5 * 2**attempt)

    async def _post(self, path: str, payload: dict[str, Any]) -> None:
        await asyncio.to_thread(self._post_sync, path, payload)

    async def start_run(self, run: dict[str, Any]) -> None:
        await self._post("/v1/runs", run)

    async def add_steps(self, run_id: str, steps: list[dict[str, Any]]) -> None:
        await self._post(f"/v1/runs/{run_id}/steps", {"steps": steps})

    async def finish_run(
        self, run_id: str, status: str, outcome: str | None = None,
        oracle_detail: dict[str, Any] | None = None,
    ) -> None:
        await self._post(
            f"/v1/runs/{run_id}/finish",
            {"status": status, "outcome": outcome, "oracle_detail": oracle_detail},
        )
