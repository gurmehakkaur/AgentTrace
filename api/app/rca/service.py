from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app import db
from app.rca.agent import analyze
from app.rca.compact import build_prompt
from app.rca.lineage import lineage
from app.rca.memory import failing_fields, recall_patterns
from app.rca.report import report_view
from app.workflows.registry import Workflow


async def generate_report(workspace: str, run: dict[str, Any], workflow: Workflow, client: Any) -> dict[str, Any]:
    """Analyse a failed run, store the report and return it as the API shows it.
    Raises RcaError if the agent cannot produce a valid report."""
    path = lineage(run["steps"], workflow.oracle_keys)
    recalled = await recall_patterns(workspace, run["workflow"], failing_fields(run))  # [] if memory is off
    prompt = build_prompt(run, path, workflow.oracle_keys, recalled)
    result = await analyze(run, prompt, client, {p["experiment"] for p in recalled})
    report_id = uuid4().hex
    doc = {"run": run["id"], "lineage": path, "created_at": datetime.now(UTC).isoformat(),
           "recalled": recalled, **result}
    await db.create_rca_report(workspace, report_id, doc)
    return report_view({**doc, "id": report_id})
