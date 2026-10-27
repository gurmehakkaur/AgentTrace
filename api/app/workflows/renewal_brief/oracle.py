"""The oracle is code, not an LLM: ground truth comes straight from the data source, and a run
passes only if the writer's footer matches it."""

import json
import re
from typing import Any

from app.workflows.renewal_brief.graph import MAX_DRAFTS
from app.workflows.renewal_brief.tools import OPEN_STATUSES, BaseTools

_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


async def ground_truth(tools: BaseTools, account_id: str) -> dict[str, Any]:
    """Exact answer for one account, via the undecorated fetchers (never recorded as steps)."""
    tickets = await tools.fetch_tickets(account_id)
    opps = await tools.fetch_opportunities(account_id)
    return {
        "open_tickets": sum(t["status"] in OPEN_STATUSES for t in tickets),
        "open_pipeline_usd": round(sum(o["Amount"] or 0 for o in opps if not o["IsClosed"]), 2),
    }


def parse_footer(draft: str) -> dict[str, Any] | None:
    """The last fenced JSON block of the brief, or None if missing or malformed."""
    blocks = _FENCED_JSON.findall(draft or "")
    try:
        return json.loads(blocks[-1]) if blocks else None
    except json.JSONDecodeError:
        return None


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check(final_state: dict[str, Any], truth: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Pass if open_tickets equals truth, pipeline is within 1%, and the critic loop approved
    within the revision cap."""
    footer = parse_footer(final_state.get("draft", ""))
    got_tickets = footer.get("open_tickets") if footer else None
    got_pipeline = footer.get("open_pipeline_usd") if footer else None

    tickets_ok = _is_number(got_tickets) and got_tickets == truth["open_tickets"]
    expected = truth["open_pipeline_usd"]
    pipeline_ok = _is_number(got_pipeline) and abs(got_pipeline - expected) <= 0.01 * abs(expected)
    loop_ok = final_state.get("verdict") == "approve" and final_state.get("drafts", 0) <= MAX_DRAFTS

    detail = {
        "truth": truth,
        "footer": footer,
        "open_tickets_ok": tickets_ok,
        "pipeline_ok": pipeline_ok,
        "critic_loop_ok": loop_ok,
        "drafts": final_state.get("drafts", 0),
    }
    return tickets_ok and pipeline_ok and loop_ok, detail
