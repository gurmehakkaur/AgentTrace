"""Failure-pattern memory on SurrealDB Agent Memory.

Agent Memory is NOT the trace store (that stays in SurrealDB tables). It holds one short
paragraph per VERIFIED root cause: an experiment showed that editing a step moved the success
rate. Recalled into the next root-cause analysis, it lets the agent say "seen before".

Rules:
- Only verified patterns are stored (treatment beats control and passes at least 3 runs). An
  unverified hypothesis would poison later analyses.
- Never raw prompts or payloads: a redacted paragraph built from the hypothesis and the numbers.
- One scope per SOURCE RUN, under the workspace and workflow:
  ws/<workspace>/workflow/<name>/run/<run id>. Never crossing organizations is then a matter of
  the prefix, and forgetting a run is exact (scopes.forget). A parent scope does not include its
  children, so recall passes the explicit list of scopes, which we keep on the experiments.
- Everything here is best effort. If memory is not configured or is down, remember and forget
  return False/0 and recall returns []. An experiment or analysis never fails because of it.
- The text carries its own provenance ("experiment <id>, run <id>") because a recall hit holds
  only id, score, source and text.
"""

import logging
import re
from typing import Any

from agenttrace_sdk import redact
from surrealdb_memory import AsyncMemory

from app import db
from app.config import get_settings

log = logging.getLogger(__name__)

INFER = "full"  # the docs' example setting for remember()
MIN_TREATMENT_PASSES = 3

_SCOPE_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_EXPERIMENT = re.compile(r"experiment ([0-9a-f]{32})")
_RUN = re.compile(r"run ([0-9a-f]{32})")
_AGENT = re.compile(r"traced to the (\S+) step")


def scope_for(workspace: str, workflow: str) -> str:
    return f"ws/{_SCOPE_UNSAFE.sub('_', workspace)}/workflow/{_SCOPE_UNSAFE.sub('_', workflow)}"


def run_scope(workspace: str, workflow: str, run_id: str) -> str:
    return f"{scope_for(workspace, workflow)}/run/{_SCOPE_UNSAFE.sub('_', run_id)}"


def _open() -> AsyncMemory | None:
    s = get_settings()
    if not s.memory_configured:
        return None
    return AsyncMemory(s.spectron_context, endpoint=s.spectron_endpoint, api_key=s.spectron_api_key,
                       timeout=20.0, max_retries=2)


def is_verified(control: dict[str, int], treatment: dict[str, int]) -> bool:
    """Worth remembering: the edit helped (a higher pass rate than control) and passed at least
    MIN_TREATMENT_PASSES runs. Small N is directional, so this stays deliberately modest."""
    if treatment["total"] == 0 or treatment["pass"] < MIN_TREATMENT_PASSES:
        return False
    return treatment["pass"] / treatment["total"] > control["pass"] / max(control["total"], 1)


def failing_fields(run: dict[str, Any]) -> list[str]:
    """Oracle checks that failed, by name (`open_tickets_ok: false` -> `open_tickets`)."""
    detail = run.get("oracle_detail") or {}
    return [k[:-3] for k, v in detail.items() if k.endswith("_ok") and v is False]


def pattern_text(
    *, workflow: str, agent: str, node_run_idx: int, fields: list[str], patch_keys: list[str],
    hypothesis: str | None, experiment_id: str, run_id: str, control: dict[str, int],
    treatment: dict[str, int], p: float | None,
) -> str:
    cause, _ = redact((hypothesis or f"the {agent} step produced a wrong value").strip())
    p_text = f", Fisher p={p:.4f}" if p is not None else ""
    return (
        f"In workflow {workflow}, the failure on {', '.join(fields) or 'the oracle check'} was traced to the "
        f"{agent} step (node run {node_run_idx}). {cause} Editing {', '.join(patch_keys)} at that step moved the "
        f"success rate from {control['pass']}/{control['total']} to {treatment['pass']}/{treatment['total']} "
        f"(directional{p_text}). Source: experiment {experiment_id}, run {run_id}."
    )


async def _ensure_scope(mem: AsyncMemory, scope: str) -> None:
    try:
        await mem.scopes.register(scope, description="AgentTrace failure patterns")
    except Exception:  # already registered, most likely; a real failure surfaces on remember()
        pass


async def remember_experiment(
    workspace: str, experiment: dict[str, Any], run: dict[str, Any], report: dict[str, Any] | None
) -> str | None:
    """Store the pattern behind a verified experiment. Returns the scope it went into (the caller
    keeps it on the experiment so recall can find it), or None if nothing was stored."""
    if not is_verified(experiment["control"], experiment["treatment"]):
        return None
    mem = _open()
    if mem is None:
        return None
    k = experiment["fork_node_run_idx"]
    agent = next((s["agent"] for s in run["steps"] if s["node_run_idx"] == k), "unknown")
    hypothesis = next(
        (c["hypothesis"] for c in (report or {}).get("candidates", []) if c["node_run_idx"] == k), None
    )
    text = pattern_text(
        workflow=run["workflow"], agent=agent, node_run_idx=k, fields=failing_fields(run),
        patch_keys=sorted(experiment["edit_patch"]), hypothesis=hypothesis, experiment_id=experiment["id"],
        run_id=run["id"], control=experiment["control"], treatment=experiment["treatment"],
        p=experiment["stats"]["fisher_p"],
    )
    labels = [f"workflow={run['workflow']}", f"agent_role={agent}", f"experiment={experiment['id']}",
              f"run={run['id']}", *[f"failure_class={f}" for f in failing_fields(run)]]
    scope = run_scope(workspace, run["workflow"], run["id"])
    try:
        await _ensure_scope(mem, scope)
        await mem.remember(text, infer=INFER, scopes=[scope], labels=labels)
        return scope
    except Exception as exc:
        log.warning("agent memory remember failed: %s", type(exc).__name__)
        return None
    finally:
        await mem.close()


async def recall_patterns(workspace: str, workflow: str, fields: list[str], k: int = 3) -> list[dict[str, Any]]:
    """Past verified patterns for this workspace and workflow, best match first. Hits without a
    parseable experiment id are skipped: a pattern with no provenance cannot be linked or checked."""
    mem = _open()
    if mem is None:
        return []
    try:
        # The prefix is what keeps this workspace's memory its own: only scopes under it are read.
        prefix = scope_for(workspace, workflow) + "/run/"
        scopes = [s for s in await db.list_memory_scopes(workspace) if s.startswith(prefix)]
        if not scopes:
            return []
        query = f"{workflow} root cause of failure on {' '.join(fields) or 'the oracle check'}"
        # Ask for more than we keep: hits with no provenance (extracted entities) and repeats are
        # dropped below.
        response = await mem.recall(query, k=k * 3, mode="hybrid", lens=scopes)
        found: dict[str, dict[str, Any]] = {}
        for hit in response.hits:
            experiment = _EXPERIMENT.search(hit.text)
            if experiment is None or experiment.group(1) in found:
                continue
            run = _RUN.search(hit.text)
            agent = _AGENT.search(hit.text)
            found[experiment.group(1)] = {
                "experiment": experiment.group(1), "run": run.group(1) if run else None,
                "agent_role": agent.group(1) if agent else None, "text": hit.text, "score": hit.score,
            }
        return list(found.values())[:k]
    except Exception as exc:
        log.warning("agent memory recall failed: %s", type(exc).__name__)
        return []
    finally:
        await mem.close()


async def forget_run(workspace: str, workflow: str, run_id: str) -> int:
    """Forget everything remembered from a run (used when a run is deleted): its scope, with the
    pattern and what memory extracted from it. Returns how many items were removed."""
    mem = _open()
    if mem is None:
        return 0
    try:
        return (await mem.scopes.forget(run_scope(workspace, workflow, run_id))).forgotten
    except Exception as exc:
        log.warning("agent memory forget failed: %s", type(exc).__name__)
        return 0
    finally:
        await mem.close()


async def forget_scopes(scopes: list[str]) -> tuple[int, int]:
    """Forget these scopes entirely (a deleted run's remembered patterns). Returns (items removed,
    scopes that could not be forgotten): the caller records a failure instead of hiding it."""
    if not scopes:
        return 0, 0
    mem = _open()
    if mem is None:
        return 0, len(scopes)
    removed = failed = 0
    try:
        for scope in scopes:
            try:
                removed += (await mem.scopes.forget(scope)).forgotten
            except Exception as exc:
                failed += 1
                log.warning("agent memory forget failed: %s", type(exc).__name__)
    finally:
        await mem.close()
    return removed, failed
