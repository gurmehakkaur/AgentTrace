"""The replay worker: run your own agents for AgentTrace, next to your code.

AgentTrace cannot re-run an agent it did not build. To fork a run from your harness, you run a worker where
your code lives. It connects OUT to the API (nothing connects in), takes one job at a time, calls your own
`resume` function to run the rest of the workflow live, and reports what happened. The server records each
attempt, counts k/N for the run with your change and the run without it, and works out the p-value, labelled
directional. Live steps are sampled, never deterministic; that is why each side is repeated.

    worker = Worker("https://<api>", "at_live_...")          # a key with the `worker` scope
    worker.register("renewal-brief", resume, oracle=check, safe_to_rerun=True)
    await worker.run_forever()

`resume(state, rec)` gets the state to continue from (the recording up to the fork point, with the change
applied for the run that has it) and a recorder. Run your agents from there, record each turn with
`await rec.turn(...)`, and return the final state. Your `oracle` decides pass or fail on that state, in your
process, as in oracle.py.

`safe_to_rerun` has no default and must be True. A fork runs your agents again, live, several times. We cannot
see inside your code, so YOU are saying that doing so is safe: no real emails sent, no real payments, or
those tools are mocked. If you cannot say that, do not run a worker for this workflow.
"""

import asyncio
import copy
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agenttrace_sdk._http import ApiClient, ApiError
from agenttrace_sdk.adapters.core import RunRecorder
from agenttrace_sdk.oracle import Check
from agenttrace_sdk.sinks import ListSink

log = logging.getLogger("agenttrace.worker")

Resume = Callable[[dict[str, Any], RunRecorder], Awaitable[dict[str, Any]]]


@dataclass
class _Registered:
    resume: Resume
    oracle: Check


class Worker:
    def __init__(
        self, base_url: str = "", api_key: str = "", *, name: str = "worker", client: Any = None, poll_seconds: float = 3.0,
    ) -> None:
        self._client = client or ApiClient(base_url, api_key)
        self.name = name
        self._poll = poll_seconds
        self._flows: dict[str, _Registered] = {}

    def register(self, workflow: str, resume: Resume, *, oracle: Check, safe_to_rerun: bool) -> None:
        if safe_to_rerun is not True:
            raise ValueError(
                "safe_to_rerun must be True. A fork runs your agents again, live; say so only if that is safe "
                "(no real side effects, or they are mocked)."
            )
        self._flows[workflow] = _Registered(resume, oracle)

    async def run_once(self) -> bool:
        """Take one job, run it, report it. False if there was no job."""
        if not self._flows:
            raise RuntimeError("register at least one workflow first")
        job = (await self._client.call("POST", "/v1/worker/claim", {"workflows": list(self._flows), "worker": self.name}))["job"]
        if job is None:
            return False
        flow = self._flows[job["workflow"]]
        sink = ListSink()
        outcome, detail = "error", None
        try:
            async with RunRecorder(sink, job["workflow"], oracle=flow.oracle) as rec:
                final = await flow.resume(copy.deepcopy(job["state"]), rec)
                rec.final_state = final if isinstance(final, dict) else {}
            ended = sink.runs[rec.id]
            outcome, detail = ended["outcome"] or "error", ended["oracle_detail"]
        except Exception as exc:  # your function failed: that attempt is an error run, and the worker carries on
            log.warning("job %s: resume raised %s", job["experiment"], type(exc).__name__)
            detail = {"verdict": {"kind": "code", "name": "resume", "passed": None, "reason": f"Your resume function raised {type(exc).__name__}"}}
        try:
            await self._client.call("POST", "/v1/worker/results", {
                "experiment": job["experiment"], "claim": job["claim"], "arm": job["arm"], "i": job["i"],
                "outcome": outcome, "oracle_detail": detail, "steps": sorted(sink.steps, key=lambda s: s["idx"])[:300],
            })
        except ApiError as exc:
            if exc.status != 409:  # 409: the job's time ran out and another worker has it. Nothing to do.
                raise
            log.warning("job %s: no longer ours (%s)", job["experiment"], exc.detail)
        return True

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        """Poll for jobs until `stop` is set. A failed call waits and tries again; it never ends the loop."""
        delay = self._poll
        while stop is None or not stop.is_set():
            try:
                busy = await self.run_once()
                delay = self._poll
                if busy:
                    continue
            except ApiError as exc:
                log.warning("worker call failed: %s", exc.detail)
                delay = min(delay * 2, 60.0)
            await asyncio.sleep(delay)
