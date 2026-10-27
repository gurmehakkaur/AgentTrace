"""Phase 1 smoke test: apply the schema, insert a fake run with 3 steps, read it back by graph
traversal, and check list_forks is empty. Uses a throwaway workspace and removes it afterwards.

    cd api && .venv/bin/python scripts/smoke_db.py
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402


async def main() -> None:
    ws, run_id = f"smoke-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex
    await db.apply_schema()
    print("schema applied")
    try:
        await db.create_run(ws, run_id, "smoke_workflow", "2026-01-01T00:00:00+00:00")
        steps = [
            {"idx": i, "node_run_idx": i, "agent": f"agent{i}", "kind": "llm", "origin": "recorded",
             "run": run_id, "tokens_in": 10, "tokens_out": 5}
            for i in (1, 2, 3)
        ]
        print("added:", await db.add_steps(ws, run_id, steps))
        print("added again (expect 0):", await db.add_steps(ws, run_id, steps))
        run = await db.get_run_with_steps(ws, run_id)
        print("steps via graph traversal:", [(s["idx"], s["agent"]) for s in run["steps"]])
        print("forks of a fresh run:", await db.list_forks(ws, run_id))
        print("other workspace sees:", await db.get_run_with_steps("smoke-other", run_id))
    finally:
        await db.purge_workspace(ws)
        print("cleaned up", ws)


if __name__ == "__main__":
    asyncio.run(main())
