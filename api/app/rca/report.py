from typing import Any

from app.rca.agent import Candidate


def report_view(doc: dict[str, Any]) -> dict[str, Any]:
    """A stored RCA report as the API returns it. SurrealDB drops fields stored as None;
    validating through Candidate restores them."""
    return {
        "id": doc["id"], "run": doc["run"], "model": doc["model"], "created_at": doc["created_at"],
        "lineage": doc["lineage"], "dropped_quotes": doc.get("dropped_quotes", 0),
        "tokens_in": doc["tokens_in"], "tokens_out": doc["tokens_out"], "recalled": doc.get("recalled", []),
        "verification": doc.get("verification"), "verdict_idx": doc.get("verdict_idx"),
        "verified_by": doc.get("verified_by", []),
        "candidates": [Candidate.model_validate(c).model_dump() for c in doc["candidates"]],
    }
