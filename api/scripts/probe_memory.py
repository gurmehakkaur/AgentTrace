"""Probe the Agent Memory service with YOUR endpoint, context and key.

    cd api && .venv/bin/python scripts/probe_memory.py

Checks reachability, auth, scope registration, remember, recall (with provenance in the text)
and an exact forget (by the run's scope), in a throwaway scope that it cleans up. Prints structure, never the key. Run this
first if remembering or recalling misbehaves.
"""

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from surrealdb_memory import AsyncMemory  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.rca import memory  # noqa: E402


async def main() -> int:
    s = get_settings()
    print(f"endpoint set={bool(s.spectron_endpoint)} context={s.spectron_context!r} key set={bool(s.spectron_api_key)}")
    if not s.memory_configured:
        print("FAIL: SPECTRON_ENDPOINT / SPECTRON_CONTEXT / SPECTRON_API_KEY are not all set in .env")
        return 1

    mem = AsyncMemory(s.spectron_context, endpoint=s.spectron_endpoint, api_key=s.spectron_api_key, timeout=30.0)
    exp, run = uuid.uuid4().hex, uuid.uuid4().hex
    scope = memory.run_scope(f"test-probe-{uuid.uuid4().hex[:6]}", "probe_workflow", run)
    text = (f"In workflow probe_workflow, the failure on open_tickets was traced to the planner step (node run 1). "
            f"Editing plan moved the success rate from 0/3 to 3/3. Source: experiment {exp}, run {run}.")
    try:
        print("health:", await mem.health())
        who = await mem.whoami()
        print("whoami ok:", type(who).__name__)
        print("register scope:", (await mem.scopes.register(scope, description="probe")).__class__.__name__, scope)
        r = await mem.remember(text, infer=memory.INFER, scopes=[scope], labels=[f"experiment={exp}", f"run={run}"])
        print("remember ->", {k: v for k, v in vars(r).items() if k != "extraction"} if hasattr(r, "__dict__") else r)

        hits = []
        for attempt in range(1, 7):  # indexing may lag a moment
            resp = await mem.recall("probe_workflow root cause of failure on open_tickets", k=5, mode="hybrid", lens=[scope])
            hits = resp.hits
            print(f"recall attempt {attempt}: {len(hits)} hit(s)")
            if hits:
                break
            time.sleep(3)
        for h in hits:
            print("  hit:", {"id": h.id, "score": round(h.score, 3), "source": h.source, "has_experiment_id": exp in h.text, "has_run_id": run in h.text})
        ok_recall = any(exp in h.text for h in hits)
        print("recalled with provenance:", ok_recall)

        forgotten = (await mem.scopes.forget(scope)).forgotten
        print("scopes.forget(run scope) removed:", forgotten, "items")
        after = (await mem.recall("probe_workflow open_tickets", k=5, lens=[scope])).hits
        left = len([h for h in after if exp in h.text])
        print("hits still recallable after forget:", left)
        return 0 if (ok_recall and forgotten and not left) else 1
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {str(exc)[:300]}")
        return 1
    finally:
        try:
            await mem.scopes.forget(scope)
            print("cleaned scope")
        except Exception as exc:
            print("scope cleanup:", type(exc).__name__)
        await mem.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
