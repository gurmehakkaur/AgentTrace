"""Mint an ingest key for a workspace and write it straight into .env.

    cd api && .venv/bin/python scripts/create_workspace_key.py                      # DEV_WORKSPACE_ID
    cd api && .venv/bin/python scripts/create_workspace_key.py --workspace org_abc --force

A workspace is a Clerk organization id (shown on the /runs page). Runs recorded with the key
appear for members of that organization.

The key is stored hashed in SurrealDB and written to AGENTTRACE_INGEST_KEY in the repo-root
.env. It is never printed, so it never lands in a terminal or chat log. Refuses to overwrite an
existing key unless --force.
"""

import argparse
import asyncio
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.auth import KEY_PREFIX, hash_key  # noqa: E402
from app.config import REPO_ROOT, get_settings  # noqa: E402

ENV_VAR = "AGENTTRACE_INGEST_KEY"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="mint a new key even if one is set")
    ap.add_argument("--workspace", help="workspace id (a Clerk org id); default DEV_WORKSPACE_ID")
    args = ap.parse_args()

    env_file = REPO_ROOT / ".env"
    text = env_file.read_text()
    existing = re.search(rf"^{ENV_VAR}=(.*)$", text, re.MULTILINE)
    if existing and existing.group(1).strip() and not args.force:
        print(f"{ENV_VAR} is already set in .env; use --force to mint another")
        return 1

    workspace = args.workspace or get_settings().dev_workspace_id or "dev"
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    await db.apply_schema()
    await db.upsert_workspace(workspace, "Dev workspace" if workspace == "dev" else workspace)
    await db.create_api_key(workspace, key[:12], hash_key(key), "create_workspace_key.py")

    line = f"{ENV_VAR}={key}"
    text = re.sub(rf"^{ENV_VAR}=.*$", lambda _: line, text, flags=re.MULTILINE) if existing \
        else text.rstrip("\n") + f"\n{line}\n"
    env_file.write_text(text)
    print(f"Minted key {key[:12]}... for workspace {workspace!r} and wrote it to .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
