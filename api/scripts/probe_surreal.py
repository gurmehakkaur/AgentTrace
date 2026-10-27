"""Probe: confirm the surrealdb SDK flow works against YOUR instance.

    cd api && .venv/bin/python scripts/probe_surreal.py

Prints what worked, never the credentials. Run this first if /health says db:false.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import surrealdb  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402


async def main() -> int:
    s = get_settings()
    print(f"surrealdb sdk {getattr(surrealdb, '__version__', '?')}")
    print(f"url set={bool(s.surreal_url)} ns={s.surreal_ns!r} db={s.surreal_db!r} "
          f"auth={'token' if s.surreal_token else 'user/pass@' + s.surreal_auth_level}")
    if not s.surreal_configured:
        print("FAIL: SURREAL_* not fully set in .env")
        return 1
    try:
        async with db.connect(s) as conn:
            print("connected + authenticated + use(ns, db): ok")
            print("RETURN 1 ->", await conn.query("RETURN 1;"))
            print("server version ->", await conn.version())
    except Exception as exc:
        print(f"FAIL at connect/auth/query: {type(exc).__name__}: {exc}")
        print("Hints: SURREAL_URL is the bare wss://host (SDK adds /rpc); "
              "try SURREAL_AUTH_LEVEL=namespace|database, or use SURREAL_TOKEN.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
