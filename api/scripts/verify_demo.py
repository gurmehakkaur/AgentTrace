"""Auto-verify the top root-cause candidates of the demo's featured run, live.

    cd api && .venv/bin/python scripts/verify_demo.py            # workspace "demo"
    cd api && .venv/bin/python scripts/verify_demo.py --workspace dev

Tests up to 2 candidates that carry a concrete edit with 3 live runs per arm (12 runs), then
re-ranks them by the measured improvement. The result is stored on the report (and shown on
/demo), whatever it turns out to be.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.rca import verify  # noqa: E402
from app.rca.report import report_view  # noqa: E402
from app.runtime import get_runtime  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="demo")
    args = ap.parse_args()

    run_id = await db.get_featured_run_id(args.workspace)
    stored = await db.get_latest_rca_report(args.workspace, run_id) if run_id else None
    if stored is None:
        print("no featured run with a root-cause report in that workspace")
        return 1
    report = report_view(stored)
    for i, c in enumerate(report["candidates"]):
        edit = "has an edit" if c.get("proposed_edit") else "no concrete edit"
        print(f"  candidate {i}: node run {c['node_run_idx']}  conf {c['confidence']:.2f}  {edit}")

    client, tools = get_runtime()
    await verify.start(args.workspace, report, client=client, tools=tools, created_by="seed")
    await verify._TASKS[report["id"]]

    done = report_view(await db.get_latest_rca_report(args.workspace, run_id))
    v = done["verification"]
    print(f"\nverification {v['status']}; ranking {v.get('ranking')}; verdict candidate {done['verdict_idx']}")
    for it in v["items"]:
        if it.get("experiment_id"):
            print(f"  candidate {it['candidate_idx']}: control {it['control']['pass']}/{it['control']['total']} "
                  f"-> treatment {it['treatment']['pass']}/{it['treatment']['total']}  "
                  f"verified={it['verified']}  ({it['status']})")
        else:
            print(f"  candidate {it['candidate_idx']}: not tested ({it['error']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
