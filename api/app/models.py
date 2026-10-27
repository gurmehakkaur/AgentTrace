"""Request models. Step mirrors the SDK's Step record (sdk/agenttrace_sdk/context.py): the SDK
is stdlib-only, so this is the API-side Pydantic copy that validates what arrives at ingest.

Experiment and RcaReport models arrive with the phases that use them."""

from typing import Any, Literal

from pydantic import BaseModel, Field

# Becomes part of a SurrealDB record id, so keep it boring.
_ID = r"^[A-Za-z0-9_-]{8,64}$"


class Step(BaseModel):
    run: str | None = None  # taken from the URL, never trusted from the body
    idx: int = Field(ge=1)
    node_run_idx: int = Field(ge=1)
    agent: str
    kind: Literal["llm", "tool"]
    origin: Literal["recorded", "replayed", "edited", "live"]
    model: str | None = None
    params: dict[str, Any] = {}
    input: Any = None
    output: Any = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any = None
    side_effect: bool | None = None
    state_after: dict[str, Any] | None = None
    reads: list[str] = []
    writes: list[str] = []
    content_hash: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    redactions: list[dict[str, str]] = []


class RunCreate(BaseModel):
    id: str = Field(pattern=_ID)
    workflow: str = Field(min_length=1, max_length=128)
    origin: str = "recorded"
    started_at: str


class StepBatch(BaseModel):
    steps: list[Step] = Field(max_length=100)


class RunFinish(BaseModel):
    status: Literal["ok", "error"]
    outcome: Literal["pass", "fail", "error"] | None = None
    oracle_detail: dict[str, Any] | None = None


class ExperimentCreate(BaseModel):
    run_id: str
    fork_node_run_idx: int = Field(ge=1)
    # Treatment edit: top-level state keys to overwrite at the fork point. The control arm
    # forks at the same point with no edit, so an experiment needs one.
    edit: dict[str, Any] = Field(min_length=1)
    n: int = Field(ge=1, le=100)  # the real ceiling is MAX_N, enforced with a clear message


class WorkerClaim(BaseModel):
    workflows: list[str] = Field(min_length=1, max_length=50)  # what this worker can run
    worker: str = Field(default="worker", max_length=64)


class WorkerResult(BaseModel):
    experiment: str
    claim: str
    arm: Literal["control", "treatment"]
    i: int = Field(ge=1)
    outcome: Literal["pass", "fail", "error"]
    oracle_detail: dict[str, Any] | None = None
    # The live turns the worker ran. Numbered from 1 here; the server places them after the fork point.
    steps: list[Step] = Field(default=[], max_length=300)
