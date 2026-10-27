"""A tiny JSON-over-HTTP client for the AgentTrace API. Stdlib only (urllib in a worker thread).

Retries connection errors and 5xx. The key goes in a Bearer header and never appears in an error message."""

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Any


class ApiError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class ApiClient:
    def __init__(self, base_url: str, api_key: str, *, retries: int = 2, timeout: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._retries = retries
        self._timeout = timeout

    def request(self, method: str, path: str, payload: Any = None) -> Any:
        request = urllib.request.Request(
            self._base + path,
            data=None if payload is None else json.dumps(payload, default=str).encode(),
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            method=method,
        )
        for attempt in range(self._retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                    body = resp.read()
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as exc:
                if exc.code < 500 or attempt == self._retries:
                    raw = exc.read()[:300].decode(errors="replace")
                    try:
                        detail = json.loads(raw).get("detail", raw)
                    except ValueError:
                        detail = raw
                    raise ApiError(exc.code, str(detail)) from None
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == self._retries:
                    raise ApiError(0, f"could not reach the API: {type(exc).__name__}") from None
            time.sleep(0.5 * 2**attempt)

    async def call(self, method: str, path: str, payload: Any = None) -> Any:
        return await asyncio.to_thread(self.request, method, path, payload)
