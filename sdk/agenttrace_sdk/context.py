"""The Step record and the "current run / current node" state kept in contextvars.

contextvars let the LLM and tool wrappers find the active run and node inside async code
without threading parameters through every function. asyncio tasks copy the context when they
are created, so `asyncio.gather` inside a node still sees the right node.

Numbering is 1-based everywhere: `idx` (step within the run) and `node_run_idx` (which
execution of an agent). A node run is one execution of an agent and may hold several steps;
a writer that runs twice in a writer/critic loop is node runs 3 and 5, not "the writer".
"""

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any

from agenttrace_sdk.sinks import Sink


@dataclass
class Step:
    run: str
    idx: int
    node_run_idx: int
    agent: str
    kind: str  # 'llm' | 'tool'
    origin: str  # 'recorded' here; Phase 5 writes 'replayed' | 'edited' | 'live'
    model: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    input: Any = None
    output: Any = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any = None
    side_effect: bool | None = None
    state_after: dict[str, Any] | None = None  # only on the last step of a node run
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    content_hash: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    redactions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RunContext:
    def __init__(
        self, run_id: str, workflow: str, origin: str, sink: Sink, *,
        start_idx: int = 0, start_node_run_idx: int = 0,
        mocks: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        self.id = run_id
        self.workflow = workflow
        self.origin = origin
        self.sink = sink
        # Set by the caller inside `trace_run` once the oracle has run; sent on finish.
        self.outcome: str | None = None
        self.oracle_detail: dict[str, Any] | None = None
        # Side-effecting tools by name; a live run may only call those that have a mock here.
        self.mocks = mocks or {}
        # A fork continues numbering after the steps it copied.
        self._idx = start_idx
        self._node_runs = start_node_run_idx

    def next_idx(self) -> int:
        self._idx += 1
        return self._idx

    def next_node_run_idx(self) -> int:
        self._node_runs += 1
        return self._node_runs


class NodeContext:
    def __init__(
        self, name: str, reads: tuple[str, ...], writes: tuple[str, ...], node_run_idx: int
    ) -> None:
        self.name = name
        self.reads = reads
        self.writes = writes
        self.node_run_idx = node_run_idx
        self.steps: list[Step] = []


current_run: ContextVar[RunContext | None] = ContextVar("agenttrace_run", default=None)
current_node: ContextVar[NodeContext | None] = ContextVar("agenttrace_node", default=None)
