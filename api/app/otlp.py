"""OpenTelemetry in. Anything that already emits GenAI traces can point at AgentTrace and get runs it can
look at, without wrapping its code.

One trace is one run. `invoke_agent` spans are agents; `chat` (and text_completion / generate_content) spans
are model calls and `execute_tool` spans are tool calls, and those are the steps. Any other span is skipped.
A model or tool span belongs to the nearest `invoke_agent` span above it; all of an agent span's steps are
one agent turn. A step with no agent span above it is named by its own `gen_ai.agent.name`, or by its span
name, and a tool call with neither joins the agent of the step before it.

The GenAI attribute names are marked Development in the OpenTelemetry conventions, so they may change; they
are read here as: gen_ai.operation.name, gen_ai.agent.name, gen_ai.request.model, gen_ai.usage.input_tokens,
gen_ai.usage.output_tokens, gen_ai.input.messages, gen_ai.output.messages, gen_ai.system_instructions,
gen_ai.tool.name, gen_ai.tool.call.arguments, gen_ai.tool.call.result. Message content may be a JSON string
or structured. Content the exporter did not record (it is opt-in in the conventions) simply stays empty.
Not verified against a real exporter: only against the OTLP JSON shape in the specification.

OpenTelemetry carries no shared state between agents. A run from here can be looked at and given a verdict,
but not forked, unless an agent span carries `agenttrace.state_after` (JSON): the state when that turn ended.
"""

import json
from datetime import UTC, datetime
from typing import Any

from app.importer import ImportRun, ImportStep

MAX_STEPS = 300
_MODEL_OPS = {"chat", "text_completion", "generate_content"}
_TOOL_OPS = {"execute_tool"}
_TRACE_ID = set("0123456789abcdef")


def _value(v: dict[str, Any]) -> Any:
    """An OTLP AnyValue: {"stringValue": ...}, {"intValue": "12"} (int64 as a string), arrays, key-value lists."""
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in v:
            return v[key]
    if "intValue" in v:
        return int(v["intValue"])
    if "arrayValue" in v:
        return [_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {kv["key"]: _value(kv.get("value", {})) for kv in v["kvlistValue"].get("values", [])}
    return None


def _attrs(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {a["key"]: _value(a.get("value", {})) for a in items or []}


def _loose(v: Any) -> Any:
    """Message and tool content arrive as a JSON string or as structured data. Keep structure when it is there."""
    if isinstance(v, str) and v[:1] in ("[", "{"):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _int(v: Any) -> int:
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


class _Span:
    def __init__(self, raw: dict[str, Any], service: str | None) -> None:
        self.trace = str(raw["traceId"]).lower()
        self.id = str(raw["spanId"]).lower()
        self.parent = (str(raw.get("parentSpanId") or "").lower()) or None
        self.name = str(raw.get("name") or "")
        self.start = int(raw.get("startTimeUnixNano") or 0)
        self.end = int(raw.get("endTimeUnixNano") or 0)
        self.attrs = _attrs(raw.get("attributes"))
        self.service = service
        self.op = self.attrs.get("gen_ai.operation.name")

    @property
    def is_agent(self) -> bool:
        return self.op == "invoke_agent"

    @property
    def is_tool(self) -> bool:
        return self.op in _TOOL_OPS or (self.op is None and "gen_ai.tool.name" in self.attrs)

    @property
    def is_step(self) -> bool:
        return self.op in _MODEL_OPS or self.is_tool


def _agent_above(span: _Span, by_id: dict[str, _Span]) -> _Span | None:
    seen = 0
    parent = by_id.get(span.parent or "")
    while parent is not None and seen < 50:
        if parent.is_agent:
            return parent
        parent = by_id.get(parent.parent or "")
        seen += 1
    return None


def _one_trace(spans: list[_Span]) -> ImportRun | str:
    """The run for one trace, or the reason it has none."""
    spans.sort(key=lambda s: s.start)
    by_id = {s.id: s for s in spans}
    agents = [s for s in spans if s.is_agent]
    steps = [s for s in spans if s.is_step]
    if not steps:
        return "no GenAI model or tool spans (gen_ai.operation.name chat or execute_tool)"
    if len(steps) > MAX_STEPS:
        return f"more than {MAX_STEPS} steps in one trace"

    labels: dict[Any, int] = {}  # which turn a step belongs to
    out: list[ImportStep] = []
    free = 0
    previous: tuple[str, Any] | None = None  # agent name and turn label of the step before
    for s in steps:
        above = _agent_above(s, by_id)
        if above is not None:
            agent = above.attrs.get("gen_ai.agent.name") or above.name or "agent"
            label: Any = ("agent", above.id)
        else:
            named = s.attrs.get("gen_ai.agent.name")
            if named is None and s.is_tool and previous is not None:
                agent, label = previous  # a tool call with no agent of its own belongs to the step before it
            else:
                agent = str(named or s.name or "agent")
                if previous is None or previous[0] != agent or previous[1][0] != "free":
                    free += 1
                label = ("free", free)
        previous = (agent, label)
        labels.setdefault(label, len(labels) + 1)

        if s.is_tool:
            args = _loose(s.attrs.get("gen_ai.tool.call.arguments"))
            step = ImportStep(
                agent=agent[:128], kind="tool", node=labels[label],
                tool_name=str(s.attrs.get("gen_ai.tool.name") or s.name or "tool")[:128],
                tool_args=args if isinstance(args, dict) else ({"value": args} if args is not None else None),
                tool_result=_loose(s.attrs.get("gen_ai.tool.call.result")),
            )
        else:
            given: dict[str, Any] = {}
            system = _loose(s.attrs.get("gen_ai.system_instructions"))
            messages = _loose(s.attrs.get("gen_ai.input.messages", s.attrs.get("gen_ai.prompt")))
            if system is not None:
                given["system"] = system
            if messages is not None:
                given["messages"] = messages
            step = ImportStep(
                agent=agent[:128], kind="llm", node=labels[label], input=given or None,
                output=_loose(s.attrs.get("gen_ai.output.messages", s.attrs.get("gen_ai.completion"))),
                model=str(s.attrs.get("gen_ai.request.model") or s.attrs.get("gen_ai.response.model") or "") or None,
                tokens_in=_int(s.attrs.get("gen_ai.usage.input_tokens")), tokens_out=_int(s.attrs.get("gen_ai.usage.output_tokens")),
            )
        step.latency_ms = max(0, (s.end - s.start) // 1_000_000) if s.end >= s.start else 0
        carried = _loose((above.attrs if above is not None else s.attrs).get("agenttrace.state_after"))
        step.state_after = carried if isinstance(carried, dict) else None
        out.append(step)

    root = next((s for s in spans if s.parent is None or s.parent not in by_id), spans[0])
    service = next((s.service for s in spans if s.service), None)
    first = min((s.start for s in spans if s.start), default=0)
    started = datetime.fromtimestamp(first / 1e9, UTC).isoformat() if first else None
    return ImportRun(workflow=str(service or root.name or "otel")[:128], started_at=started, steps=out)


def traces_to_runs(body: dict[str, Any]) -> tuple[list[tuple[str, ImportRun]], int, str]:
    """(trace id, run) for every trace that has GenAI steps, how many spans were not accepted, and why.
    Raises ValueError, KeyError or TypeError when the body is not OTLP JSON."""
    by_trace: dict[str, list[_Span]] = {}
    for resource in body.get("resourceSpans", []):
        service = _attrs(resource.get("resource", {}).get("attributes")).get("service.name")
        for scope in resource.get("scopeSpans", []):
            for raw in scope.get("spans", []):
                span = _Span(raw, service)
                by_trace.setdefault(span.trace, []).append(span)
    runs: list[tuple[str, ImportRun]] = []
    rejected = 0
    reason = ""
    for trace, spans in by_trace.items():
        valid = len(trace) == 32 and set(trace) <= _TRACE_ID and trace != "0" * 32
        made = _one_trace(spans) if valid else "not a valid trace id"
        if isinstance(made, str):
            rejected += len(spans)
            reason = reason or made
        else:
            runs.append((trace, made))
    return runs, rejected, reason
