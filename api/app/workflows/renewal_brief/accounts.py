"""Which Era accounts make a good demo? One that shows the planted bug: enough open tickets that a
wrong answer is visibly wrong, a solved ticket so the buggy filter has something to find, and an
open opportunity. Used by scripts/pick_account.py and the generalization benchmark."""

from collections import Counter
from typing import Any

from app.workflows.renewal_brief.tools import OPEN_STATUSES, EraTools


async def find_candidates(era: EraTools, min_open: int = 3) -> list[dict[str, Any]]:
    """Qualifying accounts, fewest open tickets first (smaller prompts)."""
    orgs = await era.get_all(era.zendesk, "/api/v2/organizations.json?per_page=100", "organizations")
    external_id = {o["id"]: o["external_id"] for o in orgs}
    tickets = await era.get_all(era.zendesk, "/api/v2/tickets.json?per_page=100", "tickets")
    opps = await era.soql("SELECT AccountId, Amount FROM Opportunity WHERE IsClosed = false")

    open_tickets, solved = Counter(), Counter()
    for t in tickets:
        account = external_id.get(t["organization_id"])
        if t["status"] in OPEN_STATUSES:
            open_tickets[account] += 1
        elif t["status"] == "solved":
            solved[account] += 1
    open_opps = Counter(o["AccountId"] for o in opps)

    found = [
        {"account_id": a, "open_tickets": open_tickets[a], "solved_tickets": solved[a], "open_opps": open_opps[a]}
        for a in open_tickets
        if open_tickets[a] >= min_open and solved[a] >= 1 and open_opps[a] >= 1
    ]
    return sorted(found, key=lambda c: (c["open_tickets"], c["account_id"]))
