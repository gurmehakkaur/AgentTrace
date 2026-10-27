"""Fork a recorded run at a node run, then run the rest live.

Recorded steps replay exactly (read from the database, zero API calls). Forked steps re-run
live, so their outputs are sampled fresh each time. We never call them deterministic; the
experiment runner measures them.

Given a parent run, a fork point k (a node run, 1-based) and an optional edit:

  node runs 1..k-1   copied from the parent as origin 'replayed'   (no network, 0 tokens)
  node run k         no edit: copied as 'replayed'
                     edit:    ONE synthetic step, origin 'edited', holding the patch (not re-run)
  node runs k+1..    run live through the same runner used for recording, origin 'live'

State at the fork point is the parent's recorded state_after of node run k, with the edit's
top-level keys overwritten. The control arm is the same fork with no edit, so control and
treatment differ in exactly one thing.
"""

import inspect
import logging
from dataclasses import dataclass
from typing import Any, Literal

from agenttrace_sdk import SideEffectBlocked, redact, trace_run

from app import db
from app.config import DEMO_EFFORT, DEMO_MODEL
from app.runner.run import run_to_end
from app.runner.sink import DbSink
from app.workflows.registry import REGISTRY, Workflow

log = logging.getLogger(__name__)

Arm = Literal["control", "treatment"]


class ModelPinError(RuntimeError):
    """The recording used model settings that differ from what a live suffix would use."""


def _copy(step: dict[str, Any], run_id: str, origin: str) -> dict[str, Any]:
    # Copied steps were not executed in this run, so they cost nothing here.
    return {**step, "run": run_id, "origin": origin, "tokens_in": 0, "tokens_out": 0, "latency_ms": 0}


def _check_model_pinned(steps: list[dict[str, Any]]) -> None:
    """Live steps must use the recorded model and params. Our nodes take them from config, so
    refuse if config no longer matches the recording instead of silently swapping models."""
    for s in steps:
        # Only steps a model actually ran: edited steps hold a patch, replayed ones were checked
        # when they were first recorded or run.
        if s["kind"] == "llm" and s["origin"] in ("recorded", "live") and (
            s["model"] != DEMO_MODEL or s["params"].get("output_config") != {"effort": DEMO_EFFORT}
        ):
            raise ModelPinError(
                f"recorded {s['model']!r} {s['params']}, but live steps would use "
                f"{DEMO_MODEL!r} effort {DEMO_EFFORT!r}"
            )


def _side_effecting_tools(tools: Any, mocks: dict[str, Any]) -> list[str]:
    return [
        name for name, member in inspect.getmembers(tools)
        if getattr(member, "side_effect", False) is True and name not in mocks
    ]


def _edited_step(
    run_id: str, idx: int, k: int, recorded_last: dict[str, Any], edit: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    step = {
        "run": run_id, "idx": idx, "node_run_idx": k, "agent": recorded_last["agent"],
        "kind": recorded_last["kind"], "origin": "edited", "model": recorded_last["model"],
        "params": {}, "input": None, "output": {"edited_updates": edit},
        "tool_name": None, "tool_args": None, "tool_result": None, "side_effect": None,
        "state_after": state, "reads": recorded_last["reads"], "writes": recorded_last["writes"],
        "content_hash": "", "tokens_in": 0, "tokens_out": 0, "latency_ms": 0,
    }
    clean, found = redact(step)  # stored copy only; the live state below stays raw
    clean["redactions"] = found
    return clean


@dataclass(frozen=True)
class ForkPlan:
    workflow: Workflow
    k: int
    state: dict[str, Any]  # what the live suffix starts from
    prefix: list[dict[str, Any]]  # recorded steps of node runs before k
    node_k: list[dict[str, Any]]  # recorded steps of node run k
    start_idx: int  # numbering the live steps continue from


async def prepare_fork(
    workspace: str,
    parent_run_id: str,
    fork_node_run_idx: int,
    edit: dict[str, Any] | None,
    tools: Any,
    mocks: dict[str, Any] | None = None,
) -> ForkPlan:
    """Validate a fork and work out what it will copy and restore. Creates nothing.

    Raises LookupError (parent not in workspace, or unregistered workflow), ValueError (bad
    fork point or edit), ModelPinError, SideEffectBlocked.
    """
    parent = await db.get_run_with_steps(workspace, parent_run_id)
    if parent is None:
        raise LookupError("parent run not found")
    workflow = REGISTRY.get(parent["workflow"])
    if workflow is None:
        raise LookupError(f"workflow {parent['workflow']!r} is not registered for forking")

    steps = parent["steps"]
    k = fork_node_run_idx
    node_k = [s for s in steps if s["node_run_idx"] == k]
    if not node_k:
        raise ValueError(f"parent run has no node run {k}")
    recorded_state = node_k[-1]["state_after"]
    if not isinstance(recorded_state, dict):
        raise ValueError(f"node run {k} has no recorded state_after to restore")
    if edit is not None:
        undeclared = sorted(set(edit) - set(node_k[-1]["writes"]))
        if undeclared:
            raise ValueError(f"edit keys {undeclared} are not writes of node run {k}")

    _check_model_pinned(steps)
    blocked = _side_effecting_tools(tools, mocks or {})
    if blocked:
        raise SideEffectBlocked(f"side-effecting tools without a mock: {blocked}")

    prefix = [s for s in steps if s["node_run_idx"] < k]
    prefix_last_idx = max((s["idx"] for s in prefix), default=0)
    # Live steps continue numbering after what was copied: node run k is either kept as-is
    # (its steps keep their idx) or collapsed into one edited step right after the prefix.
    start_idx = prefix_last_idx + 1 if edit is not None else max(s["idx"] for s in prefix + node_k)
    return ForkPlan(workflow, k, {**recorded_state, **(edit or {})}, prefix, node_k, start_idx)


async def run_fork(
    workspace: str,
    parent_run_id: str,
    fork_node_run_idx: int,
    edit: dict[str, Any] | None,
    arm: Arm,
    *,
    client: Any,
    tools: Any,
    mocks: dict[str, Any] | None = None,
    experiment_id: str | None = None,
) -> str:
    """Create a fork run and return its id. The run's outcome ('pass' | 'fail' | 'error') is
    stored on the run; a failure after the run exists is recorded, not raised. Validation
    errors (see prepare_fork) are raised before any run is created."""
    mocks = mocks or {}
    plan = await prepare_fork(workspace, parent_run_id, fork_node_run_idx, edit, tools, mocks)
    workflow, k = plan.workflow, plan.k

    run_id: str | None = None
    try:
        async with trace_run(
            workflow.name, DbSink(workspace), origin="live", mocks=mocks,
            start_idx=plan.start_idx, start_node_run_idx=k,
        ) as run:
            run_id = run.id
            copied = [_copy(s, run.id, "replayed") for s in plan.prefix]
            if edit is None:
                copied += [_copy(s, run.id, "replayed") for s in plan.node_k]
            else:
                copied.append(_edited_step(run.id, plan.start_idx, k, plan.node_k[-1], edit, plan.state))
            await db.add_steps(workspace, run.id, copied)
            await db.create_fork_edge(workspace, run.id, parent_run_id, k, arm, experiment_id)

            final = await run_to_end(workflow.build_nodes(), workflow.next_node, plan.state, client, tools)
            passed, detail = workflow.check(final, await workflow.ground_truth(final, tools))
            run.outcome, run.oracle_detail = ("pass" if passed else "fail"), detail
    except Exception as exc:
        if run_id is None:
            raise
        log.warning("fork %s ended with %s", run_id, type(exc).__name__)  # recorded as 'error'
    assert run_id is not None
    return run_id
