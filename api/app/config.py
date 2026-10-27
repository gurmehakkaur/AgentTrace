"""Env vars, model ids and budget caps. Model ids live here and nowhere else."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

# Local dev reads the repo-root .env. Real environment variables win (override=False),
# and on Render there is no file, so this is a no-op there.
load_dotenv(REPO_ROOT / ".env")

# Models
DEMO_MODEL = "claude-haiku-5-5"
# claude-haiku-5-5 rejects non-default temperature/top_p/top_k (400), and anthropic 2.x has no
# `temperature` argument. Sampling stays at the API default; effort is the control we set.
DEMO_EFFORT = "low"
# The RCA agent also runs on Haiku (cheaper, fast). Unlike Sonnet 5.5, Haiku 5.5 accepts a forced
# tool_choice (probed), so report_candidates can be forced.
RCA_MODEL = "claude-haiku-5-5"
RCA_EFFORT = "medium"

DB_CONNECT_TIMEOUT_S = 5.0


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    env: str
    web_origins: list[str]

    surreal_url: str
    surreal_ns: str
    surreal_db: str
    surreal_user: str
    surreal_pass: str
    surreal_token: str
    surreal_auth_level: str

    dev_workspace_id: str  # local scripts only; the API itself never uses it
    demo_workspace_id: str  # the one workspace the public /demo routes may serve
    clerk_issuer: str
    spectron_endpoint: str  # SurrealDB Agent Memory (formerly "Spectron")
    spectron_context: str
    spectron_api_key: str
    clerk_jwks_url: str

    tools_backend: str
    demo_account_id: str

    max_n: int
    max_tokens_per_experiment: int
    daily_experiments_per_user: int

    @property
    def memory_configured(self) -> bool:
        return bool(self.spectron_endpoint and self.spectron_context and self.spectron_api_key)

    @property
    def surreal_configured(self) -> bool:
        has_creds = bool(self.surreal_token or (self.surreal_user and self.surreal_pass))
        return bool(self.surreal_url and self.surreal_ns and self.surreal_db and has_creds)


def get_settings() -> Settings:
    """Read the environment at call time so tests can monkeypatch it."""
    origins = [o.strip().rstrip("/") for o in _env("WEB_ORIGINS", "http://localhost:3000").split(",")]
    return Settings(
        env=_env("ENV", "dev"),
        web_origins=[o for o in origins if o],
        surreal_url=_env("SURREAL_URL"),
        surreal_ns=_env("SURREAL_NS"),
        surreal_db=_env("SURREAL_DB"),
        surreal_user=_env("SURREAL_USER"),
        surreal_pass=_env("SURREAL_PASS"),
        surreal_token=_env("SURREAL_TOKEN"),
        surreal_auth_level=_env("SURREAL_AUTH_LEVEL", "root").lower(),
        dev_workspace_id=_env("DEV_WORKSPACE_ID"),
        demo_workspace_id=_env("DEMO_WORKSPACE_ID", "demo"),
        clerk_issuer=_env("CLERK_ISSUER").rstrip("/"),
        clerk_jwks_url=_env("CLERK_JWKS_URL"),
        spectron_endpoint=_env("SPECTRON_ENDPOINT").rstrip("/"),
        spectron_context=_env("SPECTRON_CONTEXT"),
        spectron_api_key=_env("SPECTRON_API_KEY"),
        tools_backend=_env("TOOLS_BACKEND", "fixtures").lower(),
        demo_account_id=_env("DEMO_ACCOUNT_ID", "acct-1"),
        max_n=_env_int("MAX_N", 8),
        max_tokens_per_experiment=_env_int("MAX_TOKENS_PER_EXPERIMENT", 500_000),
        daily_experiments_per_user=_env_int("DAILY_EXPERIMENTS_PER_USER", 10),
    )
