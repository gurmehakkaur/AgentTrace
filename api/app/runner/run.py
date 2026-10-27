"""The one loop that runs a workflow's nodes. Recording uses it now; the replay engine will
reuse it in Phase 5 to run the live suffix from a restored state."""

from collections.abc import Callable, Mapping
from typing import Any

from agenttrace_sdk import TracedLLM

END = "__end__"
MAX_NODE_RUNS = 12  # safety net: the renewal brief needs at most 8


async def run_to_end(
    nodes: Mapping[str, Callable[..., Any]],
    next_node: Callable[[dict[str, Any]], str],
    state: dict[str, Any],
    client: Any,
    tools: Any,
) -> dict[str, Any]:
    """Run `next_node(state)` repeatedly until END; return the final state.

    Each node gets its own TracedLLM named after it. Call inside `trace_run` to record.
    """
    for _ in range(MAX_NODE_RUNS):
        name = next_node(state)
        if name == END:
            return state
        state = state | await nodes[name](state, TracedLLM(client, name), tools)
    raise RuntimeError(f"workflow did not finish within {MAX_NODE_RUNS} node runs")
