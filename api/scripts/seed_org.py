"""Fill an organisation's workspace with more runs, for a presentation. Additive, tagged, and removable.

    cd api && .venv/bin/python scripts/seed_org.py --workspace org_XXXX --dry-run   # say what it would add
    cd api && .venv/bin/python scripts/seed_org.py --workspace org_XXXX             # add it
    cd api && .venv/bin/python scripts/seed_org.py --workspace org_XXXX --remove     # take exactly that back out

What it adds:
  * more runs of the renewal brief: copies of that workspace's own recorded run, at other times (the same bug, again)
  * runs of a second workflow, "support-triage (sample data)", from a harness the server does not run: each with its
    agents, state, and a verdict from a check written in code. SAMPLE DATA: the workflow name says so.
  * experiments on three of those runs, done through the real worker code (the SDK Worker, and the server's own
    claim and report), so every fork run and every k of N is produced by the real paths: one fix that works (5 of 5),
    one that does not (0 of 5), and a hint with too few runs (3 of 3, p = 0.1).

Everything it makes carries seed = "presentation". --remove deletes those runs (with their forks and experiments) and
nothing else. No model is called: no tokens are spent.
"""

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

from app import db  # noqa: E402
from app.rca import memory  # noqa: E402
from app.experiments import worker as server  # noqa: E402
from app.importer import ImportRun, ImportStep, import_run  # noqa: E402
from app.models import Step, WorkerResult  # noqa: E402
from app.routes.ingest import prepare_step  # noqa: E402
from agenttrace_sdk import Worker, run_oracle  # noqa: E402

TAG = "presentation"
FLOW = "support-triage (sample data)"
NOW = datetime.now(UTC)


def ago(hours: float = 0, minutes: float = 0) -> datetime:
    return NOW - timedelta(hours=hours, minutes=minutes)


# --- the sample workflow --------------------------------------------------------------------

TICKETS = [  # (hours ago, ticket, category the router chose)
    (30, "I want a refund for order 1182, it arrived broken", "shipping"),
    (25, "Where is my parcel? Order 1190", "shipping"),
    (20, "Please refund my duplicate charge, order 1204", "shipping"),
    (15, "Refund order 1215, wrong size", "shipping"),
    (9, "Can I change my delivery address? Order 1221", "shipping"),
    (3, "I need a refund for order 1230", "shipping"),
]
REPLIES = {
    "billing": "We have started your refund and it will reach you in 3 to 5 working days.",
    "shipping": "Your order is on its way and should arrive in 2 days.",
}


def right_reply(state):
    """The check the customer wrote: a refund request must get a refund reply, and nothing else may."""
    asked = "refund" in state["ticket"].lower()
    gave = "refund" in state["reply"].lower()
    if asked and gave:
        return True, "the reply handles the refund"
    if asked:
        return False, "the customer asked for a refund and the reply never mentions one"
    if gave:
        return False, "the reply promises a refund nobody asked for"
    return True, "no refund was needed"


right_reply.__name__ = "refund_handled"


def ticket_run(ticket: str, category: str, hours: float) -> ImportRun:
    reply = REPLIES[category]
    s1 = {"ticket": ticket, "category": category}
    s2 = {**s1, "reply": reply}
    s3 = {**s2, "approved": True}
    asked = "refund" in ticket.lower()
    gave = "refund" in reply.lower()
    outcome = "pass" if asked == gave else "fail"
    return ImportRun(
        workflow=FLOW, started_at=ago(hours).isoformat(), outcome=outcome,
        oracle_detail={"verdict": {"kind": "code", "name": "refund_handled", "passed": outcome == "pass", "reason": right_reply({**s3})[1]}},
        steps=[
            ImportStep(agent="router", node=1, model="claude-haiku-5-5", input={"ticket": ticket}, output={"category": category},
                       state_after=s1, writes=["category"], tokens_in=140, tokens_out=12),
            ImportStep(agent="responder", node=2, kind="tool", tool_name="lookup_order", tool_args={"order": ticket.split("order ")[-1][:4]}, tool_result={"found": True}),
            ImportStep(agent="responder", node=2, model="claude-haiku-5-5", input={"ticket": ticket, "category": category}, output=reply,
                       state_after=s2, writes=["reply"], tokens_in=210, tokens_out=40),
            ImportStep(agent="reviewer", node=3, model="claude-haiku-5-5", input={"reply": reply}, output={"approved": True},
                       state_after=s3, writes=["approved"], tokens_in=90, tokens_out=8),
        ],
    )


async def resume_flow(state, rec):
    """The customer's code, run from the fork point: the responder if it has not run yet, then the reviewer."""
    if "reply" not in state:
        reply = REPLIES[state["category"]]
        state = {**state, "reply": reply}
        await rec.turn("responder", input={"category": state["category"]}, output=reply, state_after=state, writes=["reply"],
                       tool_calls=[{"name": "lookup_order", "args": {"order": "sample"}, "result": {"found": True}}], tokens_in=210, tokens_out=40)
    state = {**state, "approved": True}
    await rec.turn("reviewer", input={"reply": state["reply"]}, output={"approved": True}, state_after=state, writes=["approved"], tokens_in=90, tokens_out=8)
    return state


class InProcess:
    """The SDK worker's client, answered by the server's own functions: the same claim and report the API runs."""

    def __init__(self, workspace: str):
        self.ws = workspace

    async def call(self, method, path, payload=None):
        if path == "/v1/worker/claim":
            return {"job": await server.claim(self.ws, payload["workflows"], payload["worker"])}
        return await server.report(self.ws, WorkerResult(**payload))


# (index into TICKETS, turn to fork, edit, n): a fix that works, one that does not, a hint
EXPERIMENTS = [
    (0, 1, {"category": "billing"}, 5, 40),
    (2, 2, {"reply": "Sorry about that. We are looking into it and will be in touch."}, 5, 35),
    (3, 1, {"category": "billing"}, 3, 30),
]


# --- the work -------------------------------------------------------------------------------

async def tag(workspace: str, runs_before: set[str], exps_before: set[str]) -> tuple[int, int]:
    async with db.connect() as c:
        rows = await c.query("SELECT id FROM run WHERE workspace = $ws", {"ws": workspace})
        new_runs = [r["id"].id for r in rows if r["id"].id not in runs_before]
        for rid in new_runs:
            await c.query("UPDATE type::record('run', $id) MERGE { seed: $t }", {"id": rid, "t": TAG})
        exps = await c.query("SELECT id FROM experiment WHERE workspace = $ws", {"ws": workspace})
        new_exps = [e["id"].id for e in exps if e["id"].id not in exps_before]
        for eid in new_exps:
            await c.query("UPDATE type::record('experiment', $id) MERGE { seed: $t }", {"id": eid, "t": TAG})
    return len(new_runs), len(new_exps)


async def set_times(run_id: str, started: datetime, took_s: int = 38) -> None:
    async with db.connect() as c:
        await c.query("UPDATE type::record('run', $id) MERGE $m", {"id": run_id, "m": {"started_at": started.isoformat(), "ended_at": (started + timedelta(seconds=took_s)).isoformat()}})


async def add_renewal_copies(workspace: str) -> int:
    recorded = [r for r in await db.list_runs(workspace, 50, "recorded") if r["workflow"] == "renewal_brief" and not r.get("seed")]
    if not recorded:
        print("  no renewal_brief run in this workspace to copy: skipped")
        return 0
    source = await db.get_run_with_steps(workspace, recorded[-1]["id"])
    made = 0
    for hours in (28, 21, 7):
        run_id = uuid.uuid4().hex
        started = ago(hours)
        await db.create_run(workspace, run_id, source["workflow"], started.isoformat())
        steps = [prepare_step(Step(**{k: v for k, v in s.items() if k in Step.model_fields}), run_id) for s in source["steps"]]
        await db.add_steps(workspace, run_id, steps)
        await db.finish_run(workspace, run_id, "ok", source.get("outcome"), source.get("oracle_detail"))
        await set_times(run_id, started)
        made += 1
    return made


async def add_triage(workspace: str) -> list[str]:
    ids = []
    for hours, ticket, category in TICKETS:
        run = ticket_run(ticket, category, hours)
        made = await import_run(workspace, run)
        await set_times(made["id"], ago(hours), 31)
        ids.append(made["id"])
    return ids


async def add_experiments(workspace: str, run_ids: list[str]) -> None:
    worker = Worker(client=InProcess(workspace), name="seed")
    worker.register(FLOW, resume_flow, oracle=right_reply, safe_to_rerun=True)
    await run_experiments(workspace, run_ids, worker, EXPERIMENTS)


async def run_experiments(workspace: str, run_ids: list[str], worker: Worker, which: list) -> None:
    for index, turn, edit, n, minutes_after in which:
        parent = await db.get_run_with_steps(workspace, run_ids[index])
        exp_id = await server.create(workspace, {**parent, "id": run_ids[index]}, turn, edit, n, "seed")
        jobs = 0
        while await worker.run_once():
            jobs += 1
        started = ago(TICKETS[index][0]) + timedelta(minutes=minutes_after)
        await db.update_experiment(workspace, exp_id, {"created_at": started.isoformat(), "finished_at": (started + timedelta(minutes=4)).isoformat()})
        done = await db.get_experiment(workspace, exp_id)
        print(f"  experiment on run {index + 1}, turn {turn}, n={n}: {jobs} jobs, without {done['control']['pass']}/{done['control']['total']}, with {done['treatment']['pass']}/{done['treatment']['total']}")


async def remove(workspace: str) -> None:
    async with db.connect() as c:
        rows = await c.query("SELECT id FROM run WHERE workspace = $ws AND seed = $t AND kind = 'recorded'", {"ws": workspace, "t": TAG})
    scopes: list[str] = []
    for r in rows:
        deleted = await db.delete_run_cascade(workspace, r["id"].id)
        scopes += (deleted or {}).get("memory_scopes", [])
    if scopes:
        await memory.forget_scopes(scopes)
    async with db.connect() as c:  # anything tagged that the cascade did not reach
        await c.query("DELETE run WHERE workspace = $ws AND seed = $t", {"ws": workspace, "t": TAG})
        await c.query("DELETE experiment WHERE workspace = $ws AND seed = $t", {"ws": workspace, "t": TAG})
    print(f"removed {len(rows)} seeded runs, with their forks and experiments")


async def resume(workspace: str, original: str) -> int:
    """Pick up a run of this script that stopped halfway: tag what it already made (an update, nothing is deleted or
    copied again) and let the worker finish the experiments it left open. `original` is the workspace's own recorded
    run from before the seeding, which is never tagged."""
    memory._open = lambda: None
    async with db.connect() as c:
        runs = await c.query("SELECT id, workflow, kind, started_at, seed FROM run WHERE workspace = $ws", {"ws": workspace})
    mine = [r for r in runs if not r.get("seed") and (r["workflow"] == FLOW or (r["workflow"] == "renewal_brief" and r["kind"] == "recorded" and not r["id"].id.startswith(original)))]
    async with db.connect() as c:
        for r in mine:
            await c.query("UPDATE type::record('run', $id) MERGE { seed: $t }", {"id": r["id"].id, "t": TAG})
        exps = await c.query("SELECT * FROM experiment WHERE workspace = $ws AND mode = 'worker' AND workflow = $f", {"ws": workspace, "f": FLOW})
        for e in exps:
            await c.query("UPDATE type::record('experiment', $id) MERGE { seed: $t }", {"id": e["id"].id, "t": TAG})
    print(f"tagged {len(mine)} runs and {len(exps)} experiments that were already there")
    triage = sorted((r for r in runs if r["workflow"] == FLOW and r["kind"] == "recorded"), key=lambda r: r["started_at"])
    worker = Worker(client=InProcess(workspace), name="seed")
    worker.register(FLOW, resume_flow, oracle=right_reply, safe_to_rerun=True)
    for e in exps:
        eid = e["id"].id
        left = [t for t in e["tiles"] if t["status"] in ("queued", "running")]
        if left:
            print(f"  experiment {eid[:8]} has {len(left)} jobs left; waiting for any stale claim to expire, then finishing it")
            for _ in range(int(server.LEASE_SECONDS / 5) + 20):
                if not await worker.run_once():
                    await asyncio.sleep(5)
                if (await db.get_experiment(workspace, eid))["status"] not in ("queued", "running"):
                    break
        done = await db.get_experiment(workspace, eid)
        index = next((i for i, r in enumerate(triage) if r["id"].id == done["parent_run"]), None)
        if index is not None and index < len(TICKETS):
            wanted = next((x for x in EXPERIMENTS if x[0] == index), None)
            if wanted:
                started = ago(TICKETS[index][0]) + timedelta(minutes=wanted[4])
                await db.update_experiment(workspace, eid, {"created_at": started.isoformat(), "finished_at": (started + timedelta(minutes=4)).isoformat()})
        print(f"  experiment {eid[:8]} {done['status']}: without {done['control']['pass']}/{done['control']['total']}, with {done['treatment']['pass']}/{done['treatment']['total']}")
    # an experiment the first pass never got to
    have = {e["parent_run"] for e in await db.list_experiments(workspace) if e.get("mode") == "worker" and e.get("workflow") == FLOW}
    ids = [r["id"].id for r in triage]
    missing = [x for x in EXPERIMENTS if x[0] < len(ids) and ids[x[0]] not in have]
    if missing:
        print(f"  creating {len(missing)} experiment(s) that were never started")
        await run_experiments(workspace, ids, worker, missing)
        async with db.connect() as c:
            fresh = await c.query("SELECT id FROM experiment WHERE workspace = $ws AND mode = 'worker' AND workflow = $f AND seed = NONE", {"ws": workspace, "f": FLOW})
            for e in fresh:
                await c.query("UPDATE type::record('experiment', $id) MERGE { seed: $t }", {"id": e["id"].id, "t": TAG})
        async with db.connect() as c:  # the fork attempts of the new experiment
            for r in await c.query("SELECT id FROM run WHERE workspace = $ws AND workflow = $f AND seed = NONE", {"ws": workspace, "f": FLOW}):
                await c.query("UPDATE type::record('run', $id) MERGE { seed: $t }", {"id": r["id"].id, "t": TAG})
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--resume", action="store_true", help="finish a seeding that stopped halfway (needs --original-run)")
    ap.add_argument("--original-run", default="", help="the workspace's own recorded run from before seeding; never tagged")
    args = ap.parse_args()
    ws = args.workspace
    if not ws.startswith("org_"):
        print("The workspace must be a Clerk organization id (org_...).")
        return 2
    await db.apply_schema()
    if args.resume:
        if not args.original_run:
            print("--resume needs --original-run <the run id this workspace had before seeding>")
            return 2
        return await resume(ws, args.original_run)
    if args.remove:
        await remove(ws)
        return 0
    async with db.connect() as c:
        if await c.query("SELECT id FROM run WHERE workspace = $ws AND seed = $t LIMIT 1", {"ws": ws, "t": TAG}):
            print("This workspace is already seeded. Run with --remove first if you want to start again.")
            return 1
        runs_before = {r["id"].id for r in await c.query("SELECT id FROM run WHERE workspace = $ws", {"ws": ws})}
        exps_before = {e["id"].id for e in await c.query("SELECT id FROM experiment WHERE workspace = $ws", {"ws": ws})}
    print(f"workspace {ws}: {len(runs_before)} runs, {len(exps_before)} experiments now")
    if args.dry_run:
        print(f"would add: 3 renewal_brief copies, {len(TICKETS)} runs of {FLOW!r}, {len(EXPERIMENTS)} experiments through the real worker code")
        return 0
    # The real worker code also saves a verified fix to Agent Memory. Sample data must never go there.
    memory._open = lambda: None
    copies, ids = 0, []
    try:
        print("adding renewal_brief copies")
        copies = await add_renewal_copies(ws)
        print(f"adding {len(TICKETS)} runs of {FLOW}")
        ids = await add_triage(ws)
        print("running experiments through the worker (about 7 s a job)")
        await add_experiments(ws, ids)
    finally:  # whatever got made is tagged, even if this stopped halfway, so --remove always finds it
        runs, exps = await tag(ws, runs_before, exps_before)
    print(f"done: {copies} renewal copies, {len(ids)} support-triage runs, {exps} experiments, {runs} runs in all (fork attempts included), all tagged seed={TAG}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
