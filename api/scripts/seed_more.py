"""A second batch of sample data, so the graphs have something good in them. Same rules as seed_org.py: additive,
tagged seed = "presentation", removable with `seed_org.py --remove`, no tokens, nothing written to Agent Memory, and
NOTHING posted to Slack (the real worker code tells webhooks when a fork finishes; this script switches that off).

    cd api && .venv/bin/python scripts/seed_more.py --workspace org_XXXX --dry-run
    cd api && .venv/bin/python scripts/seed_more.py --workspace org_XXXX

It adds a third workflow, "invoice-review (sample data)", with eight runs over about three days and five experiments
run through the real worker code, one for each kind of result the app can show:

  fixed it                     the extractor fix, 5 of 5 against 0 of 5
  no difference                a fix to the wrong agent, 0 of 5 against 0 of 5
  helped, but not every run    the same fix with a flaky approver, 5 of 8 against 0 of 8
  only a hint                  3 of 3 against 0 of 3, too few runs to be sure
  made things worse            a fork made INSIDE the first fork's run, 0 of 3 against 3 of 3

The last one is a fork of a fork, so the run page draws a branch off a branch.
"""

import argparse
import asyncio
import sys
from datetime import timedelta

from seed_org import TAG, InProcess, ago, set_times, tag  # noqa: E402 (also puts api/ and sdk/ on the path)

from app import alerts, db  # noqa: E402
from app.experiments import worker as server  # noqa: E402
from app.importer import ImportRun, ImportStep, import_run  # noqa: E402
from app.rca import memory  # noqa: E402
from agenttrace_sdk import Worker  # noqa: E402

FLOW = "invoice-review (sample data)"

# (hours ago, invoice, net amount, VAT). The extractor reads the net amount and forgets the VAT: the bug.
INVOICES = [
    (70, "INV-2041", 1000.0, 180.0), (62, "INV-2047", 640.0, 0.0), (54, "INV-2052", 2500.0, 450.0), (46, "INV-2058", 310.0, 55.8),
    (38, "INV-2063", 980.0, 0.0), (27, "INV-2071", 1500.0, 270.0), (16, "INV-2079", 720.0, 129.6), (6, "INV-2084", 1200.0, 0.0),
]


def approved_is_right(state):
    """The customer's check: the amount that was approved must be the invoice total, VAT included."""
    if state.get("approved_total") is None:
        return False, "nothing was approved, so the invoice was not paid"
    if abs(state["approved_total"] - state["expected"]) < 0.005:
        return True, "the approved amount matches the invoice total"
    return False, f"approved {state['approved_total']:.2f} but the invoice total is {state['expected']:.2f} (VAT left out)"


approved_is_right.__name__ = "approved_amount_is_the_total"


def invoice_run(hours: float, number: str, net: float, vat: float) -> ImportRun:
    expected = round(net + vat, 2)
    read = net  # the bug: the extractor reads the net amount only
    s1 = {"invoice": number, "net": net, "vat": vat, "expected": expected, "total": read}
    s2 = {**s1, "valid": read > 0}
    s3 = {**s2, "approved_total": read}
    ok, reason = approved_is_right(s3)
    return ImportRun(
        workflow=FLOW, started_at=ago(hours).isoformat(), outcome="pass" if ok else "fail",
        oracle_detail={"verdict": {"kind": "code", "name": "approved_amount_is_the_total", "passed": ok, "reason": reason}},
        steps=[
            ImportStep(agent="extractor", node=1, model="claude-haiku-5-5", input={"invoice": number}, output={"total": read},
                       state_after=s1, writes=["total"], tokens_in=420, tokens_out=24),
            ImportStep(agent="validator", node=2, model="claude-haiku-5-5", input={"total": read}, output={"valid": s2["valid"]},
                       state_after=s2, writes=["valid"], tokens_in=60, tokens_out=6),
            ImportStep(agent="approver", node=3, kind="tool", tool_name="approve_payment", tool_args={"amount": read}, tool_result={"status": "queued"}),
            ImportStep(agent="approver", node=3, model="claude-haiku-5-5", input={"valid": s2["valid"]}, output={"approved_total": read},
                       state_after=s3, writes=["approved_total"], tokens_in=70, tokens_out=10),
        ],
    )


# One experiment per kind of result. (index of the run, turn to fork, the edit, n, minutes after the run, how to read it)
EXPERIMENTS = [
    (0, 1, {"total": 1180.0}, 5, 35),            # fixed it
    (2, 2, {"valid": True}, 5, 25),              # no difference: the validator was never the problem
    (3, 1, {"total": 365.8}, 8, 40),             # helped, but not every run: a flaky approver
    (5, 1, {"total": 1770.0}, 3, 20),            # only a hint
]
NESTED = (2, {"valid": False}, 3)                # a fork of the first experiment's fixed run: makes things worse

FLAKY_CALLS = {"INV-2058": {3, 6, 8}}  # the approver sometimes bounces a payment for manual review
_calls: dict[str, int] = {}


async def resume_invoice(state, rec):
    """The customer's code from the fork point: the validator if it has not run, then the approver."""
    if "valid" not in state:
        state = {**state, "valid": state["total"] > 0}
        await rec.turn("validator", input={"total": state["total"]}, output={"valid": state["valid"]}, state_after=state, writes=["valid"], tokens_in=60, tokens_out=6)
    amount = state["total"] if state["valid"] else None
    fixed = abs(state["total"] - state["expected"]) < 0.005
    if fixed and state["invoice"] in FLAKY_CALLS:  # only counts the runs that had the fix
        _calls[state["invoice"]] = _calls.get(state["invoice"], 0) + 1
        if _calls[state["invoice"]] in FLAKY_CALLS[state["invoice"]]:
            amount = None
    state = {**state, "approved_total": amount}
    await rec.turn("approver", input={"valid": state["valid"]}, output={"approved_total": amount}, state_after=state, writes=["approved_total"],
                   tool_calls=[{"name": "approve_payment", "args": {"amount": amount}, "result": {"status": "queued" if amount is not None else "held"}}],
                   tokens_in=70, tokens_out=10)
    return state


async def run_one(workspace: str, worker: Worker, parent_id: str, turn: int, edit: dict, n: int, parent_started, minutes_after: int) -> str:
    parent = await db.get_run_with_steps(workspace, parent_id)
    exp_id = await server.create(workspace, {**parent, "id": parent_id}, turn, edit, n, "seed")
    jobs = 0
    while await worker.run_once():
        jobs += 1
    started = parent_started + timedelta(minutes=minutes_after)
    await db.update_experiment(workspace, exp_id, {"created_at": started.isoformat(), "finished_at": (started + timedelta(minutes=5)).isoformat()})
    done = await db.get_experiment(workspace, exp_id)
    print(f"  fork at turn {turn} (n={n}): {jobs} jobs, without {done['control']['pass']}/{done['control']['total']}, with {done['treatment']['pass']}/{done['treatment']['total']}")
    return exp_id


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    ws = args.workspace
    if not ws.startswith("org_"):
        print("The workspace must be a Clerk organization id (org_...).")
        return 2
    if args.dry_run:
        print(f"would add: {len(INVOICES)} runs of {FLOW!r}, {len(EXPERIMENTS)} experiments and 1 fork of a fork, through the real worker code")
        return 0

    # Sample data must not reach the real world. The worker code saves a verified fix to Agent Memory and tells
    # webhooks (your Slack) when a fork finishes: both are switched off here.
    memory._open = lambda: None

    async def silent(*_a, **_k):
        return None
    alerts.notify_experiment = silent
    alerts.notify_failure = silent
    db.enable_pool()  # one process, one loop: reuse connections, so a job takes seconds, not tens of seconds

    await db.apply_schema()
    async with db.connect() as c:
        if await c.query("SELECT id FROM run WHERE workspace = $ws AND workflow = $f LIMIT 1", {"ws": ws, "f": FLOW}):
            print("This batch is already in the workspace. Run seed_org.py --remove first if you want to start again.")
            return 1
        runs_before = {r["id"].id for r in await c.query("SELECT id FROM run WHERE workspace = $ws", {"ws": ws})}
        exps_before = {e["id"].id for e in await c.query("SELECT id FROM experiment WHERE workspace = $ws", {"ws": ws})}
    print(f"workspace {ws}: {len(runs_before)} runs, {len(exps_before)} experiments now")

    try:
        print(f"adding {len(INVOICES)} runs of {FLOW}")
        ids = []
        for hours, number, net, vat in INVOICES:
            made = await import_run(ws, invoice_run(hours, number, net, vat))
            await set_times(made["id"], ago(hours), 29)
            ids.append(made["id"])
        worker = Worker(client=InProcess(ws), name="seed")
        worker.register(FLOW, resume_invoice, oracle=approved_is_right, safe_to_rerun=True)
        print("running the experiments through the worker")
        first = None
        for index, turn, edit, n, minutes in EXPERIMENTS:
            exp_id = await run_one(ws, worker, ids[index], turn, edit, n, ago(INVOICES[index][0]), minutes)
            first = first or (index, exp_id)
        # a fork made inside the first fork: from the run its treatment arm made
        index, edit, n = NESTED
        parent_exp = await db.get_experiment(ws, first[1])
        inner = next(t["run_id"] for t in parent_exp["tiles"] if t["arm"] == "treatment" and t.get("run_id"))
        print("a fork of a fork (from the first experiment's fixed run)")
        await run_one(ws, worker, inner, 2, edit, n, ago(INVOICES[first[0]][0]), 80)
    finally:
        runs, exps = await tag(ws, runs_before, exps_before)
        await db.close_pool()
    print(f"done: {len(ids)} runs, {exps} experiments, {runs} runs in all (fork attempts included), all tagged seed={TAG}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
