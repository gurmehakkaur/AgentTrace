"""A Sink that writes straight to SurrealDB, for code running inside the API process
(forks, and recording from a server-side script). External agents use the SDK's HttpSink."""

from typing import Any

from app import db


class DbSink:
    def __init__(self, workspace: str) -> None:
        self._workspace = workspace

    async def start_run(self, run: dict[str, Any]) -> None:
        kind = "recorded" if run["origin"] == "recorded" else "fork"
        await db.create_run(self._workspace, run["id"], run["workflow"], run["started_at"], kind)

    async def add_steps(self, run_id: str, steps: list[dict[str, Any]]) -> None:
        await db.add_steps(self._workspace, run_id, steps)

    async def finish_run(
        self, run_id: str, status: str, outcome: str | None = None,
        oracle_detail: dict[str, Any] | None = None,
    ) -> None:
        await db.finish_run(self._workspace, run_id, status, outcome, oracle_detail)
