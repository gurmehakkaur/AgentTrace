"""Record a LangGraph run. It reads the stream LangGraph already produces, so this module does not import
LangGraph and the SDK keeps zero dependencies.

    run_id = await record_langgraph(app.astream(inputs, stream_mode="updates"), sink, "renewal", input=inputs, oracle=check)

It drives the stream itself, so do not also iterate it elsewhere.

Probed against langgraph 1.2.17: stream_mode="updates" yields {node: update}; a list of modes yields
(mode, data); version="v2" yields {"type": "updates", "data": {...}}. All three are read. Parallel nodes in
one chunk become one turn each, in the order given.

State: LangGraph keeps the shared state inside the graph and the update stream carries only changes, so
the state shown is rebuilt by applying each update to what came before. A plain update replaces the key. For
keys that use a reducer (a list that appends), pass `reducers={"notes": operator.add}`, or the rebuilt value
is only the last update. A recorded run from an adapter is for viewing and for a verdict; it is not forkable,
because forking re-runs your agents, which only your own code can do.
"""

from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any

from agenttrace_sdk.adapters.core import RunRecorder
from agenttrace_sdk.oracle import Check
from agenttrace_sdk.sinks import Sink


def _updates(chunk: Any) -> list[tuple[str, Any]]:
    """The (node, update) pairs in one stream chunk, whatever shape LangGraph streamed it in."""
    if isinstance(chunk, tuple) and len(chunk) >= 2:
        if chunk[-2] != "updates":
            return []  # another stream mode (values, messages...): not an update
        chunk = chunk[-1]
    if isinstance(chunk, dict) and chunk.get("type") == "updates" and isinstance(chunk.get("data"), dict):
        chunk = chunk["data"]
    if not isinstance(chunk, dict):
        return []
    return [(str(node), update) for node, update in chunk.items() if not str(node).startswith("__")]


async def _each(stream: Any) -> AsyncIterator[Any]:
    if hasattr(stream, "__aiter__"):
        async for item in stream:
            yield item
    else:
        for item in stream:
            yield item


def _merge(state: dict[str, Any], update: Any, reducers: dict[str, Callable[[Any, Any], Any]]) -> dict[str, Any]:
    if not isinstance(update, dict):
        return state
    merged = dict(state)
    for key, value in update.items():
        merged[key] = reducers[key](merged[key], value) if key in reducers and key in merged else value
    return merged


async def record_langgraph(
    stream: Iterable[Any] | AsyncIterator[Any],
    sink: Sink,
    workflow: str,
    *,
    input: dict[str, Any] | None = None,
    oracle: Check | None = None,
    reducers: dict[str, Callable[[Any, Any], Any]] | None = None,
) -> str:
    """Consume a LangGraph update stream, record one turn per node, and return the run id. The final state
    is what the `oracle` checks. Errors raised by the graph propagate; the run is closed as an error first."""
    state: dict[str, Any] = dict(input or {})
    async with RunRecorder(sink, workflow, oracle=oracle) as rec:
        async for chunk in _each(stream):
            for node, update in _updates(chunk):
                before = state
                state = _merge(state, update, reducers or {})
                await rec.turn(node, input=before, output=update, state_after=state, writes=list(update) if isinstance(update, dict) else [])
        rec.final_state = state
    return rec.id
