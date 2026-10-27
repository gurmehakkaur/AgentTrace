"""Bring past runs in. People who already have agent logs send them in one simple shape and get
runs they can look at, as lines of agents. Imported runs are view only: forking and root-cause
analysis re-run the workflow's own code, which an import does not have.

The shape is deliberately small. Only `agent` is required on a step."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import db
from app.models import Step
from app.routes.ingest import prepare_step


class ImportStep(BaseModel):
    agent: str = Field(min_length=1, max_length=128)
    kind: Literal["llm", "tool"] = "llm"
    input: Any = None  # what the agent was given
    output: Any = None  # what it answered
    model: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any = None
    node: int | None = Field(default=None, ge=1)  # steps with the same number are one agent turn
    state_after: dict[str, Any] | None = None  # the shared state when this agent's turn ended
    reads: list[str] = Field(default=[], max_length=100)  # state keys the agent read
    writes: list[str] = Field(default=[], max_length=100)  # state keys it wrote: what a fork may change
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)


class ImportRun(BaseModel):
    workflow: str = Field(min_length=1, max_length=128)
    started_at: str | None = None
    outcome: Literal["pass", "fail", "error"] | None = None
    oracle_detail: dict[str, Any] | None = None
    steps: list[ImportStep] = Field(min_length=1, max_length=300)


def to_steps(run: ImportRun) -> list[Step]:
    """Number the steps, and group them into agent turns: by `node` when given, otherwise a new turn
    starts whenever the agent changes. State is kept on the last step of a turn, as the recorder does."""
    turns: list[int] = []
    for i, s in enumerate(run.steps):
        if s.node is not None:
            turns.append(s.node)
        elif i and s.agent == run.steps[i - 1].agent:
            turns.append(turns[-1])
        else:
            turns.append((turns[-1] if turns else 0) + 1)
    # renumber to 1, 2, 3 in order of first appearance
    order = {t: n for n, t in enumerate(dict.fromkeys(turns), start=1)}
    last = {t: i for i, t in enumerate(turns)}
    state = {t: next((run.steps[i].state_after for i, x in enumerate(turns) if x == t and run.steps[i].state_after), None) for t in order}
    out = []
    for i, s in enumerate(run.steps):
        t = turns[i]
        out.append(Step(
            idx=i + 1, node_run_idx=order[t], agent=s.agent, kind=s.kind, origin="recorded", model=s.model,
            input=s.input, output=s.output, tool_name=s.tool_name, tool_args=s.tool_args, tool_result=s.tool_result,
            state_after=state[t] if last[t] == i else None, reads=s.reads, writes=s.writes, tokens_in=s.tokens_in, tokens_out=s.tokens_out,
            latency_ms=s.latency_ms,
        ))
    return out


async def import_run(workspace: str, run: ImportRun, run_id: str | None = None) -> dict[str, Any]:
    """Store the run as recorded. Text is redacted and clamped exactly as ingest does it. With a `run_id`
    (an OpenTelemetry trace id) a second delivery of the same run is a no-op, so exporters may retry."""
    run_id = run_id or uuid.uuid4().hex
    created = await db.create_run(workspace, run_id, run.workflow, run.started_at or datetime.now(UTC).isoformat())
    if not created:
        return {"id": run_id, "steps": 0, "existing": True}
    steps = [prepare_step(s, run_id) for s in to_steps(run)]
    await db.add_steps(workspace, run_id, steps)
    await db.finish_run(workspace, run_id, "ok", run.outcome, run.oracle_detail)
    return {"id": run_id, "steps": len(steps)}
