"""Build the RCA prompt: one line per step for orientation, full input and output only for the
node runs on the data-lineage path. About 20k tokens at most.

Everything recorded in a trace (prompts, tool results, model text) is untrusted: a tool result
could say "ignore your instructions". So the whole trace sits inside <trace> tags, and the system
prompt tells the model to treat it as data."""

import json
from typing import Any

from app.rca.lineage import NodeRun, node_runs

MAX_CHARS = 60_000  # roughly 15k tokens of trace
FIELD_LIMITS = (4000, 1500, 600)  # per-field clip, tightened until the prompt fits


def _clip(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else f"{text[:limit]}…[+{len(text) - limit} chars clipped]"


def _summary(step: dict[str, Any]) -> str:
    if step["kind"] == "tool":
        return f"{step['tool_name']}({_clip(step['tool_args'], 100)}) -> {_clip(step['tool_result'], 100)}"
    blocks = (step["output"] or {}).get("content") or []
    text = next((b.get("text", "") for b in blocks if b.get("type") == "text"), "")
    return _clip(text.replace("\n", " "), 120)


def _detail(run: NodeRun, limit: int) -> str:
    lines = [f"### node run {run.idx} · {run.agent} (reads: {', '.join(sorted(run.reads)) or 'none'}; "
             f"writes: {', '.join(sorted(run.writes)) or 'none'})"]
    for s in run.steps:
        lines.append(f"step {s['idx']} ({s['kind']}{' ' + s['tool_name'] if s['tool_name'] else ''}, {s['origin']}):")
        if s["kind"] == "llm":
            lines += [f"  input: {_clip(s['input'], limit)}", f"  output: {_clip(s['output'], limit)}"]
        else:
            lines += [f"  args: {_clip(s['tool_args'], limit)}", f"  result: {_clip(s['tool_result'], limit)}"]
        if s["state_after"] is not None:
            lines.append(f"  state_after: {_clip(s['state_after'], limit)}")
    return "\n".join(lines)


def build_prompt(
    run: dict[str, Any], lineage_idxs: list[int], oracle_keys: tuple[str, ...],
    past_patterns: list[dict[str, Any]] | None = None,
) -> str:
    runs = node_runs(run["steps"])
    on_path = [r for r in runs if r.idx in lineage_idxs]
    overview = "\n".join(
        f"[{s['idx']}] node run {s['node_run_idx']} · {s['agent']} · {s['kind']} · {s['origin']}: {_summary(s)}"
        for s in sorted(run["steps"], key=lambda s: s["idx"])
    )
    header = (
        f"Workflow: {run['workflow']}. This run FAILED its code oracle.\n"
        f"Oracle result: {json.dumps(run.get('oracle_detail'), default=str)}\n"
        f"The failing answer is computed from state key(s): {', '.join(oracle_keys)}.\n"
        f"Node runs on the data-lineage path to it (execution order): "
        f"{' -> '.join(f'{r.idx} ({r.agent})' for r in on_path)}\n"
    )
    for limit in FIELD_LIMITS:
        body = "\n\n".join(_detail(r, limit) for r in on_path)
        trace = f"<trace>\n## All steps, one line each\n{overview}\n\n## Full detail: lineage node runs\n{body}\n</trace>"
        if len(header) + len(trace) <= MAX_CHARS:
            break
    return header + trace + _past_patterns_block(past_patterns or [])


def _past_patterns_block(patterns: list[dict[str, Any]]) -> str:
    """Earlier VERIFIED root causes from this workspace's memory, with the experiment that proved
    each. A hint, not evidence about this run, and also untrusted text (it was written by a model),
    so it is delimited and the system prompt says how to treat it."""
    if not patterns:
        return ""
    lines = "\n".join(f"- [experiment {p['experiment']}] {p['text']}" for p in patterns)
    return f"\n\n<past_patterns>\n{lines}\n</past_patterns>"
