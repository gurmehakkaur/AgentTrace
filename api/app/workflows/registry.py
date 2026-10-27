"""The workflows a fork is allowed to run. There is no endpoint that runs arbitrary code:
a run names a registered workflow, or it cannot be forked."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.workflows.renewal_brief.graph import next_node
from app.workflows.renewal_brief.nodes import build_nodes
from app.workflows.renewal_brief.oracle import check, ground_truth
from app.workflows.renewal_brief.prompts import PLANNER_SYSTEM_GOOD


@dataclass(frozen=True)
class Workflow:
    name: str
    build_nodes: Callable[[], dict[str, Any]]
    next_node: Callable[[dict[str, Any]], str]
    ground_truth: Callable[[dict[str, Any], Any], Awaitable[dict[str, Any]]]
    check: Callable[[dict[str, Any], dict[str, Any]], tuple[bool, dict[str, Any]]]
    # State keys the oracle reads its answer from: where the root-cause walk starts.
    oracle_keys: tuple[str, ...] = ()


async def _renewal_truth(state: dict[str, Any], tools: Any) -> dict[str, Any]:
    account = re.search(r"account\s+([A-Za-z0-9_-]+)", state["request"])
    if account is None:
        raise ValueError("cannot find the account id in the request")
    return await ground_truth(tools, account.group(1))


REGISTRY: dict[str, Workflow] = {
    "renewal_brief": Workflow(
        name="renewal_brief",
        # A fork never re-runs the planner (it is node run 1: copied or edited), so the
        # planner prompt here is irrelevant to forks; the good one is the safe default.
        build_nodes=lambda: build_nodes(PLANNER_SYSTEM_GOOD),
        next_node=next_node,
        ground_truth=_renewal_truth,
        check=check,
        oracle_keys=("draft",),  # the writer's brief and its JSON footer
    )
}
