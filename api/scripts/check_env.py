"""List which env vars each phase still needs. Prints names only, never values.

    python api/scripts/check_env.py            # all phases
    python api/scripts/check_env.py --phase 0  # one phase
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# Each entry is a list of alternatives: any one set var satisfies it.
PHASES: dict[int, dict[str, list[list[str]]]] = {
    0: {
        "SurrealDB Cloud": [["SURREAL_URL"], ["SURREAL_NS"], ["SURREAL_DB"], ["SURREAL_TOKEN", "SURREAL_USER"], ["SURREAL_TOKEN", "SURREAL_PASS"]],
        "Anthropic": [["ANTHROPIC_API_KEY"]],
        "Render (after first deploy)": [["WEB_ORIGINS"], ["NEXT_PUBLIC_API_URL"]],
    },
    3: {"Era (or TOOLS_BACKEND=fixtures)": [["TOOLS_BACKEND"]]},
    4: {"Ingest": [["AGENTTRACE_API_URL"], ["AGENTTRACE_INGEST_KEY"]]},
    6: {"Budget caps": [["MAX_N"], ["MAX_TOKENS_PER_EXPERIMENT"], ["DAILY_EXPERIMENTS_PER_USER"]]},
    7: {"Clerk": [["NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"], ["CLERK_SECRET_KEY"], ["CLERK_ISSUER"], ["CLERK_JWKS_URL"]]},
    11: {"SurrealDB Agent Memory": [["SPECTRON_ENDPOINT"], ["SPECTRON_API_KEY"], ["SPECTRON_CONTEXT"]]},
}


def is_set(alternatives: list[str]) -> bool:
    return any(os.environ.get(n, "").strip() for n in alternatives)


def weak_credential_warnings() -> list[str]:
    """Credentials that would pass as 'set' but are guessable. Names only, never values."""
    warnings = []
    password, user = os.environ.get("SURREAL_PASS", ""), os.environ.get("SURREAL_USER", "")
    if password:
        same_as = [n for n in ("SURREAL_USER", "SURREAL_NS", "SURREAL_DB") if os.environ.get(n) == password]
        if same_as:
            warnings.append(f"SURREAL_PASS is the same as {', '.join(same_as)}: anyone who finds the database URL can guess it")
        if len(password) < 12:
            warnings.append(f"SURREAL_PASS is only {len(password)} characters: use a long random one (at least 16)")
    return warnings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int, help="only this phase")
    args = ap.parse_args()

    missing_total = 0
    for phase, groups in sorted(PHASES.items()):
        if args.phase is not None and phase != args.phase:
            continue
        print(f"Phase {phase}")
        for group, reqs in groups.items():
            for alts in reqs:
                ok = is_set(alts)
                missing_total += 0 if ok else 1
                label = " or ".join(alts) if len(alts) > 1 else alts[0]
                print(f"  [{'x' if ok else ' '}] {group}: {label}")
    print(f"\n{missing_total} missing")
    for warning in weak_credential_warnings():
        print(f"WARNING: {warning}")
    return 1 if missing_total else 0


if __name__ == "__main__":
    sys.exit(main())
