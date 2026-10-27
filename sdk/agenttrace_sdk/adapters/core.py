"""RunRecorder: record a run from any loop or harness, without wrapping its functions.

`trace_run` + `@node` fit code you control. A harness you do not control already runs the agents, so here you
tell the recorder what happened, one agent turn at a time, and it stores the same Step records:

    async with RunRecorder(sink, "my-workflow", oracle=check) as rec:
        await rec.turn("planner", input=request, output=plan, state_after=state)
        await rec.turn("writer", output=draft, tool_calls=[{"name": "search", "args": {...}, "result": ...}])
        rec.final_state = state

Redaction happens here, before anything is sent. If the block raises, the run is closed with status "error".
With an `oracle`, the run gets a pass/fail verdict from your check when the block ends (see oracle.py).
"""

from typing import Any
from uuid import uuid4

from datetime import UTC, datetime

from agenttrace_sdk.context import Step
from agenttrace_sdk.oracle import Check, run_oracle
from agenttrace_sdk.recorder import _clean, _content_hash
from agenttrace_sdk.sinks import Sink


class RunRecorder:
    def __init__(self, sink: Sink, workflow: str, *, oracle: Check | None = None, run_id: str | None = None) -> None:
        self.sink = sink
        self.workflow = workflow
        self.oracle = oracle
        self.id = run_id or uuid4().hex
        self.final_state: dict[str, Any] | None = None  # what the oracle checks; defaults to the last state seen
        self.outcome: str | None = None
        self._idx = 0
        self._turns = 0
        self._last_state: dict[str, Any] | None = None

    async def __aenter__(self) -> "RunRecorder":
        await self.sink.start_run(
            {"id": self.id, "workflow": self.workflow, "origin": "recorded", "started_at": datetime.now(UTC).isoformat()}
        )
        return self

    async def turn(
        self,
        agent: str,
        *,
        input: Any = None,
        output: Any = None,
        model: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        state_after: dict[str, Any] | None = None,
        reads: list[str] | None = None,
        writes: list[str] | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
    ) -> None:
        """One turn of one agent: what it was given, what it answered, the tools it called, and the shared
        state when it was done. Each tool call is {"name", "args", "result"} (args a dict). `writes` are the state
        keys this agent changed: they are what a fork may edit, so a run without them cannot be forked."""
        self._turns += 1
        calls = tool_calls or []
        steps: list[Step] = []

        def new(kind: str, **fields: Any) -> Step:
            self._idx += 1
            return Step(run=self.id, idx=self._idx, node_run_idx=self._turns, agent=agent, kind=kind, origin="recorded",
                        reads=list(reads or []), writes=list(writes or []), **fields)

        # The model's own step comes first when the agent answered, or when it called no tools.
        if output is not None or input is not None or not calls:
            hits: list[dict[str, str]] = []
            clean_in = _clean("input", input, hits)
            step = new("llm", model=model, input=clean_in, output=_clean("output", output, hits),
                       tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms, redactions=hits)
            step.content_hash = _content_hash(clean_in)
            steps.append(step)
        for call in calls:
            hits = []
            args = _clean("tool_args", call.get("args") or {}, hits)
            step = new("tool", tool_name=str(call.get("name", "tool")), tool_args=args if isinstance(args, dict) else {"value": args},
                       tool_result=_clean("tool_result", call.get("result"), hits), redactions=hits)
            step.content_hash = _content_hash(step.tool_args)
            steps.append(step)
        if state_after is not None:
            self._last_state = state_after
            steps[-1].state_after = _clean("state_after", state_after, steps[-1].redactions)
        await self.sink.add_steps(self.id, [s.to_dict() for s in steps])

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is not None:
            await self.sink.finish_run(self.id, "error", "error", None)
            return
        detail = None
        if self.oracle is not None:
            state = self.final_state if self.final_state is not None else (self._last_state or {})
            self.outcome, detail = await run_oracle(self.oracle, state)
        await self.sink.finish_run(self.id, "ok", self.outcome, detail)
