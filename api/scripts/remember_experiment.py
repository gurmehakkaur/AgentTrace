"""Remember the root cause behind an EXISTING verified experiment (for experiments that finished
before Agent Memory was set up, such as the seeded demo's hero).

    cd api && .venv/bin/python scripts/remember_experiment.py --workspace demo --role hero
    cd api && .venv/bin/python scripts/remember_experiment.py --workspace dev --experiment <id>

Only verified experiments are stored (treatment beats control and passes at least 3 runs).
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.experiments.runner import view  # noqa: E402
from app.rca.memory import is_verified, remember_experiment  # noqa: E402
from app.rca.report import report_view  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--experiment")
    ap.add_argument("--role", choices=["hero", "decoy"], help="the featured demo experiment with this role")
    args = ap.parse_args()

    if args.experiment:
        doc = await db.get_experiment(args.workspace, args.experiment)
    else:
        docs = [e for e in await db.list_featured_experiments(args.workspace) if e.get("demo_role") == args.role]
        doc = docs[0] if docs else None
    if doc is None:
        print("experiment not found")
        return 1
    exp = view(doc)
    print(f"experiment {exp['id'][:8]}: control {exp['control']['pass']}/{exp['control']['total']} -> "
          f"treatment {exp['treatment']['pass']}/{exp['treatment']['total']}")
    if not is_verified(exp["control"], exp["treatment"]):
        print("not verified (treatment must beat control and pass at least 3 runs): nothing stored")
        return 1
    run = await db.get_run_with_steps(args.workspace, exp["parent_run"])
    stored = await db.get_latest_rca_report(args.workspace, exp["parent_run"])
    scope = await remember_experiment(args.workspace, exp, run, report_view(stored) if stored else None)
    if scope:
        await db.update_experiment(args.workspace, exp["id"], {"remembered": True, "memory_scope": scope})
    print(f"remembered in scope {scope}" if scope else "FAILED to remember (see the probe: scripts/probe_memory.py)")
    return 0 if scope else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
