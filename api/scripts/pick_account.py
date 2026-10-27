"""Find Era accounts for the demo: enough open tickets that a wrong answer is visibly wrong,
some solved tickets so the planted bug has something to find, and an open opportunity.

    cd api && .venv/bin/python scripts/pick_account.py

Read-only. Prints candidates; put your pick in DEMO_ACCOUNT_ID in .env.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.workflows.renewal_brief.accounts import find_candidates  # noqa: E402
from app.workflows.renewal_brief.tools import EraTools  # noqa: E402


async def main() -> None:
    candidates = await find_candidates(EraTools())
    print(f"{len(candidates)} candidates (open tickets, solved tickets, open opps):")
    for c in candidates[:8]:
        print(f"  {c['account_id']:>10}  open={c['open_tickets']:>3}  solved={c['solved_tickets']:>2}  opps={c['open_opps']}")


if __name__ == "__main__":
    asyncio.run(main())
