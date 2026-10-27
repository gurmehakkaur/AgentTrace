"""Which node runs influenced a failing output? A backward slice over the declared
reads/writes of each node run: start from the state keys the oracle checks, then walk the
node runs newest to oldest, keeping each one that wrote a key still needed and adding what it
read. A node that only reviewed (the critic) is not on the path, so it is not blamed."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NodeRun:
    idx: int
    agent: str
    steps: list[dict[str, Any]]
    reads: frozenset[str]
    writes: frozenset[str]


def node_runs(steps: list[dict[str, Any]]) -> list[NodeRun]:
    """Steps grouped by node_run_idx, oldest first. Reads/writes come from the last step."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for step in sorted(steps, key=lambda s: s["idx"]):
        grouped.setdefault(step["node_run_idx"], []).append(step)
    return [
        NodeRun(idx, group[0]["agent"], group, frozenset(group[-1]["reads"]), frozenset(group[-1]["writes"]))
        for idx, group in sorted(grouped.items())
    ]


def lineage(steps: list[dict[str, Any]], start_keys: Iterable[str]) -> list[int]:
    """Node run indexes on the path to `start_keys`, oldest first."""
    needed = set(start_keys)
    on_path: list[int] = []
    for run in reversed(node_runs(steps)):
        if run.writes & needed:
            on_path.append(run.idx)
            needed = (needed - run.writes) | run.reads
    return sorted(on_path)
