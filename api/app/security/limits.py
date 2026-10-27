"""Guards against runaway spend and oversized data.

  clamp_strings       no stored text field exceeds 32 KB (longer ones keep a sha256 of the original)
  SlidingWindowLimiter  N calls per window per user, for the endpoints that spend tokens
  enforce_daily_cap     experiments per user per UTC day (DAILY_EXPERIMENTS_PER_USER)

The rate limiter is in memory, so it is per server process: fine for one API instance, and the
daily cap (counted from the database) is the limit that holds across restarts.
"""

import asyncio
import hashlib
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from app import db
from app.config import get_settings

# One launch at a time through the cap check and the create, so two quick requests cannot both
# slip under the daily limit. Shared by every route that starts experiments.
launch_lock = asyncio.Lock()

MAX_FIELD_CHARS = 32_768
MAX_BODY_BYTES = 5_000_000


def clamp_strings(value: Any, limit: int = MAX_FIELD_CHARS) -> Any:
    """Truncate any string longer than `limit`, appending its full length and sha256 so a reader
    can tell it was cut and still compare it with the original."""
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        digest = hashlib.sha256(value.encode()).hexdigest()
        return f"{value[:limit]}…[truncated: {len(value)} chars, sha256 {digest}]"
    if isinstance(value, dict):
        return {k: clamp_strings(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [clamp_strings(v, limit) for v in value]
    return value


class SlidingWindowLimiter:
    def __init__(self, max_calls: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_calls, self.window_s, self._clock = max_calls, window_s, clock
        self._calls: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Count one call for `key`, or raise a 429 that says how long to wait."""
        now, calls = self._clock(), self._calls[key]
        while calls and calls[0] <= now - self.window_s:
            calls.popleft()
        if len(calls) >= self.max_calls:
            wait = max(1, int(calls[0] + self.window_s - now) + 1)
            raise HTTPException(
                status_code=429, headers={"Retry-After": str(wait)},
                detail=f"Too many requests: at most {self.max_calls} per {int(self.window_s)} seconds. Try again in {wait} s.",
            )
        calls.append(now)


# Calls that spend tokens: starting an experiment, running a root-cause analysis.
experiment_limiter = SlidingWindowLimiter(max_calls=6, window_s=60)
rca_limiter = SlidingWindowLimiter(max_calls=6, window_s=60)


def _next_utc_midnight(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1)


async def enforce_daily_cap(user_id: str, now: datetime | None = None, needed: int = 1) -> None:
    """429 if starting `needed` more experiments would pass this user's daily allowance."""
    now = now or datetime.now(UTC)
    cap = get_settings().daily_experiments_per_user
    since = datetime(now.year, now.month, now.day, tzinfo=UTC).isoformat()
    used = await db.count_experiments_since(user_id, since)
    if used + needed > cap:
        wait = int((_next_utc_midnight(now) - now).total_seconds())
        raise HTTPException(
            status_code=429, headers={"Retry-After": str(wait)},
            detail=f"Daily experiment limit reached ({cap} per user per day, resetting at 00:00 UTC). "
                   f"The saved demo results are always available without a limit.",
        )


# Minting keys and importing runs are cheap, but not free: a few a minute per person is plenty.
key_limiter = SlidingWindowLimiter(5, 60)
# Failure alerts: a loop that fails a thousand times must not send a thousand messages. Per workspace.
alert_limiter = SlidingWindowLimiter(10, 60)
# Any call made with a key (sending runs, a worker, an agent): 600 a minute per key, per server process.
key_use_limiter = SlidingWindowLimiter(600, 60)
webhook_limiter = SlidingWindowLimiter(10, 60)
import_limiter = SlidingWindowLimiter(20, 60)
