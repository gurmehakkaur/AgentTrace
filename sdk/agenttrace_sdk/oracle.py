"""A code oracle: your own function that says whether a run's final answer is right.

AgentTrace cannot know what "right" means for your workflow, so you tell it, in code. The check gets the
run's final state and returns True or False, optionally with a reason. The result is stored on the run as
`outcome` ("pass" or "fail") and shown as right or wrong. A check that raises, or returns something that is
not a verdict, gives outcome "error": the run is never marked right or wrong by accident, and your program
is never stopped by a bad check.

This is a check written in code, so its result is labelled kind "code". Do not describe it as more than that.
"""

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agenttrace_sdk.redaction import redact
from agenttrace_sdk.sinks import Sink

_MAX_REASON = 300


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str = ""


# A check may return True/False, (True/False, "reason"), or a Verdict, and may be sync or async.
Check = Callable[[dict[str, Any]], "bool | tuple[bool, str] | Verdict | Awaitable[bool | tuple[bool, str] | Verdict]"]


def _as_verdict(result: Any) -> Verdict:
    if isinstance(result, Verdict):
        return result
    if isinstance(result, bool):
        return Verdict(result)
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool) and isinstance(result[1], str):
        return Verdict(result[0], result[1])
    raise TypeError(f"a check must return True or False, (bool, reason) or a Verdict, not {type(result).__name__}")


def _detail(name: str, passed: bool | None, reason: str) -> dict[str, Any]:
    clean, _ = redact({"verdict": {"kind": "code", "name": name, "passed": passed, "reason": reason[:_MAX_REASON]}})
    return clean


async def run_oracle(check: Check, final_state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Run the check on the final state. Returns (outcome, oracle_detail) ready for `finish_run`."""
    name = getattr(check, "__name__", "check")
    try:
        result = check(final_state)
        if inspect.isawaitable(result):
            result = await result
        verdict = _as_verdict(result)
    except Exception as exc:  # a broken check must not break the caller, or silently pass the run
        return "error", _detail(name, None, f"The check itself failed: {type(exc).__name__}")
    return ("pass" if verdict.passed else "fail"), _detail(name, verdict.passed, verdict.reason)


async def submit_verdict(sink: Sink, run_id: str, check: Check, final_state: dict[str, Any]) -> str:
    """Give a run that is already stored (for example one that arrived over OpenTelemetry) its verdict.
    The run id of an OpenTelemetry trace is its trace id. Returns the outcome."""
    outcome, detail = await run_oracle(check, final_state)
    await sink.finish_run(run_id, "ok", outcome, detail)
    return outcome
