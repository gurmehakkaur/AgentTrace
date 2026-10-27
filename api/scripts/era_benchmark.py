"""Generalization benchmark on Era accounts: original planner prompt vs patched, N runs each.

    cd api && .venv/bin/python scripts/era_benchmark.py --workspace demo --role hero
    cd api && .venv/bin/python scripts/era_benchmark.py --workspace demo --role hero --accounts 5 --n 3

Runs the whole workflow (fresh, live) for each account and arm, so it calls Claude and Era:
5 accounts x 2 arms x 3 runs is 30 runs. The result is stored next to the hero experiment and
shown on its page, whatever it turns out to be. The demo account is left out on purpose: the
fix was found on it, so it would flatter the result.
"""

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.benchmark import run_benchmark  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.runtime import get_runtime  # noqa: E402
from app.workflows.renewal_brief.accounts import find_candidates  # noqa: E402


def table(result: dict) -> str:
    lines = [f"{'account':<10} {'original':>10} {'patched':>10}"]
    for a in result["accounts"]:
        o, p = a["original"], a["patched"]
        lines.append(f"{a['account_id']:<10} {o['pass']:>5}/{o['total']:<4} {p['pass']:>5}/{p['total']:<4}")
    t = result["totals"]
    lines.append(f"{'total':<10} {t['original']['pass']:>5}/{t['original']['total']:<4} "
                 f"{t['patched']['pass']:>5}/{t['patched']['total']:<4}")
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--role", choices=["hero", "decoy"], default="hero")
    ap.add_argument("--accounts", type=int, default=5)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--min-open", type=int, default=2, help="fewest open tickets for an account to qualify")
    args = ap.parse_args()

    await db.apply_schema()  # the benchmark table is additive and idempotent
    docs = [e for e in await db.list_featured_experiments(args.workspace) if e.get("demo_role") == args.role]
    if not docs:
        print(f"no featured {args.role} experiment in workspace {args.workspace}")
        return 1
    experiment = docs[0]

    client, tools = get_runtime()
    demo_account = get_settings().demo_account_id
    # Chosen from the account data alone (never from results): the busiest qualifying accounts.
    found = [c for c in await find_candidates(tools, min_open=args.min_open) if c["account_id"] != demo_account]
    picks = found[-args.accounts:]
    if len(picks) < args.accounts:
        print(f"only {len(picks)} qualifying accounts besides {demo_account}")
        return 1
    ids = [c["account_id"] for c in picks]
    print(f"{len(ids)} accounts {ids}, {args.n} runs per arm: {len(ids) * 2 * args.n} live runs...")

    result = await run_benchmark(ids, client, tools, n=args.n)
    print(table(result))
    errors = sum(a[arm]["errors"] for a in result["accounts"] for arm in ("original", "patched"))
    if errors:
        print(f"{errors} runs crashed (counted as not passing)")

    await db.create_benchmark(args.workspace, uuid.uuid4().hex, {
        "experiment": experiment["id"], "workflow": "renewal_brief", "created_at": datetime.now(UTC).isoformat(),
        "excluded_account": demo_account, "candidates": picks, **result,
    })
    print("stored; it now shows under the experiment")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
