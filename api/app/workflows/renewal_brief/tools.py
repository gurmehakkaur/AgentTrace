"""Read-only tools for the renewal brief: Zendesk tickets and Salesforce opportunities.

Two backends with one interface, chosen by TOOLS_BACKEND (era | fixtures):
  EraTools      Era's simulated Zendesk and Salesforce (REST, ERA-generated env vars).
  FixtureTools  fixtures/company.json, the fallback if Era is unavailable.

The @tool methods live on the shared base class. The oracle calls the undecorated
fetch_* methods directly, so ground truth never shows up as a recorded step.
"""

import json
import os
import re
from collections import Counter
from typing import Any

import httpx
from agenttrace_sdk import tool

from app.config import REPO_ROOT, get_settings

# "Open" for the oracle: everything not yet solved or closed.
OPEN_STATUSES = ("new", "open", "pending", "hold")
_SAMPLE = 10
_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _check_account_id(account_id: str) -> str:
    # account_id comes from LLM output and ends up in a SOQL string: allow nothing exotic.
    if not isinstance(account_id, str) or not _ACCOUNT_ID.match(account_id):
        raise ValueError(f"invalid account id: {account_id!r}")
    return account_id


class BaseTools:
    async def fetch_tickets(self, account_id: str) -> list[dict[str, Any]]:
        """All tickets of the account as {id, status, subject}."""
        raise NotImplementedError

    async def fetch_opportunities(self, account_id: str) -> list[dict[str, Any]]:
        """All opportunities of the account as {Id, Name, Amount, StageName, IsClosed}."""
        raise NotImplementedError

    @tool(side_effect=False)
    async def zendesk_search_tickets(self, account_id: str, statuses: list[str]) -> dict:
        tickets = [t for t in await self.fetch_tickets(_check_account_id(account_id))
                   if t["status"] in statuses]
        return {
            "account_id": account_id,
            "statuses_requested": statuses,
            "total": len(tickets),
            "by_status": dict(Counter(t["status"] for t in tickets)),
            "tickets": [
                {"id": t["id"], "status": t["status"], "subject": t["subject"][:80]}
                for t in tickets[:_SAMPLE]
            ],
        }

    @tool(side_effect=False)
    async def salesforce_list_open_opportunities(self, account_id: str) -> dict:
        opps = [o for o in await self.fetch_opportunities(_check_account_id(account_id))
                if not o["IsClosed"]]
        return {
            "account_id": account_id,
            "open_count": len(opps),
            # Summed here, in code: LLM arithmetic over amounts is flaky.
            "open_pipeline_usd": round(sum(o["Amount"] or 0 for o in opps), 2),
            "opportunities": [
                {"id": o["Id"], "name": o["Name"], "amount": o["Amount"], "stage": o["StageName"]}
                for o in opps[:_SAMPLE]
            ],
        }


class FixtureTools(BaseTools):
    def __init__(self, path: str | None = None) -> None:
        file = path or REPO_ROOT / "fixtures" / "company.json"
        with open(file) as f:
            self._accounts = json.load(f)["accounts"]

    async def fetch_tickets(self, account_id: str) -> list[dict[str, Any]]:
        return self._accounts[account_id]["tickets"]

    async def fetch_opportunities(self, account_id: str) -> list[dict[str, Any]]:
        return self._accounts[account_id]["opportunities"]


class EraTools(BaseTools):
    """Era's simulators follow the real vendors' REST shapes. Auth is the `Authorization: ...`
    header line Era generated in ZENDESK_MCP_HEADER / SALESFORCE_MCP_HEADER."""

    def __init__(self) -> None:
        self.zendesk = (os.environ["ZENDESK_BASE_URL"].rstrip("/"), _header("ZENDESK_MCP_HEADER"))
        self.salesforce = (
            os.environ["SALESFORCE_BASE_URL"].rstrip("/"),
            _header("SALESFORCE_MCP_HEADER"),
        )

    async def _get(self, system: tuple[str, dict[str, str]], path: str, **params: Any) -> dict:
        base, headers = system
        url = path if path.startswith("http") else base + path
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(url, params=params or None, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def get_all(self, system: tuple[str, dict[str, str]], path: str, key: str) -> list[dict]:
        """Follow Zendesk's `next_page` links and collect `key` from every page."""
        items: list[dict] = []
        url: str | None = path
        while url:
            page = await self._get(system, url)
            items += page[key]
            url = page.get("next_page")
        return items

    async def soql(self, query: str) -> list[dict]:
        body = await self._get(self.salesforce, "/services/data/v60.0/query", q=query)
        return body["records"]

    async def fetch_tickets(self, account_id: str) -> list[dict[str, Any]]:
        orgs = (await self._get(
            self.zendesk, "/api/v2/organizations/search.json", external_id=_check_account_id(account_id)
        ))["organizations"]
        if not orgs:
            raise LookupError(f"no Zendesk organization for account {account_id!r}")
        tickets = await self.get_all(
            self.zendesk, f"/api/v2/organizations/{orgs[0]['id']}/tickets.json?per_page=100", "tickets"
        )
        return [{"id": t["id"], "status": t["status"], "subject": t["subject"]} for t in tickets]

    async def fetch_opportunities(self, account_id: str) -> list[dict[str, Any]]:
        return await self.soql(
            "SELECT Id, Name, Amount, StageName, IsClosed FROM Opportunity "
            f"WHERE AccountId = '{_check_account_id(account_id)}'"
        )


def _header(var: str) -> dict[str, str]:
    name, _, value = os.environ[var].partition(":")
    return {name.strip(): value.strip()}


def make_tools() -> BaseTools:
    backend = get_settings().tools_backend
    if backend == "era":
        return EraTools()
    if backend == "fixtures":
        return FixtureTools()
    raise ValueError(f"TOOLS_BACKEND must be 'era' or 'fixtures', got {backend!r}")
