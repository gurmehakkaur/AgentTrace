"""Phase 0 'Done when': no .env file is ever committed. Only .env.example is tracked."""

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


pytestmark = pytest.mark.skipif(
    git("rev-parse", "--git-dir").returncode != 0, reason="not inside a git checkout"
)


@pytest.mark.parametrize("path", [".env", ".env.local", ".env.production", "web/.env.local", "api/.env"])
def test_env_files_are_gitignored(path):
    assert git("check-ignore", "-q", path).returncode == 0, f"{path} is not ignored"


def test_env_example_is_not_ignored():
    assert git("check-ignore", "-q", ".env.example").returncode == 1


def test_no_env_file_in_index_or_history():
    def is_env(p: str) -> bool:
        name = p.rsplit("/", 1)[-1]
        return name.startswith(".env") and name != ".env.example"

    tracked = git("ls-files").stdout.split()
    assert not [p for p in tracked if is_env(p)]

    history = git("log", "--all", "--name-only", "--pretty=format:").stdout.split()
    assert not [p for p in history if is_env(p)]


def test_env_example_has_no_values_for_secrets():
    text = (REPO / ".env.example").read_text()
    secrets = [
        "SURREAL_PASS", "SURREAL_TOKEN", "ANTHROPIC_API_KEY", "CLERK_SECRET_KEY",
        "SPECTRON_API_KEY", "AGENTTRACE_INGEST_KEY",
    ]
    for name in secrets:
        line = next(l for l in text.splitlines() if l.startswith(f"{name}="))
        assert line == f"{name}=", f"{name} must be empty in .env.example"
