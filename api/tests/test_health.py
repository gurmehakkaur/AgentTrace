"""Phase 0 'Done when': /health returns {"ok": true, "db": <bool>}; db is true only if a
SurrealDB connection succeeds, bounded by a 5 s timeout; CORS allows the web origin."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import DB_CONNECT_TIMEOUT_S, get_settings
from app.main import app

SURREAL_VARS = [
    "SURREAL_URL", "SURREAL_NS", "SURREAL_DB",
    "SURREAL_USER", "SURREAL_PASS", "SURREAL_TOKEN",
]


@pytest.fixture(autouse=True)
def clean_surreal_env(monkeypatch):
    """Tests must not depend on (or reach) whatever the developer put in .env."""
    for name in [*SURREAL_VARS, "ANTHROPIC_API_KEY"]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client():
    return TestClient(app)


def test_health_reports_db_true_when_connection_succeeds(client, monkeypatch):
    async def ok() -> bool:
        return True

    monkeypatch.setattr(db, "ping", ok)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "db": True, "anthropic_key": False}


def test_health_reports_whether_an_anthropic_key_is_present_without_exposing_it(client, monkeypatch):
    async def ok() -> bool:
        return True

    monkeypatch.setattr(db, "ping", ok)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-notarealkey0123456789")
    body = client.get("/health").json()
    assert body["anthropic_key"] is True and "sk-ant" not in str(body)


def test_health_is_200_with_db_false_when_db_down(client, monkeypatch):
    async def down() -> bool:
        return False

    monkeypatch.setattr(db, "ping", down)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "db": False, "anthropic_key": False}


def test_ping_is_false_when_surreal_not_configured():
    assert asyncio.run(db.ping()) is False


def test_ping_times_out_instead_of_hanging(monkeypatch):
    monkeypatch.setenv("SURREAL_URL", "wss://example.invalid")
    monkeypatch.setenv("SURREAL_NS", "ns")
    monkeypatch.setenv("SURREAL_DB", "db")
    monkeypatch.setenv("SURREAL_USER", "u")
    monkeypatch.setenv("SURREAL_PASS", "p")

    class Hangs:
        async def __aenter__(self):
            await asyncio.sleep(60)

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(db, "AsyncSurreal", lambda url: Hangs())
    started = time.monotonic()
    assert asyncio.run(db.ping(timeout=0.2)) is False
    assert time.monotonic() - started < 2


def test_default_ping_timeout_is_five_seconds():
    assert DB_CONNECT_TIMEOUT_S == 5.0


def test_ping_log_never_contains_credentials(monkeypatch, caplog):
    monkeypatch.setenv("SURREAL_URL", "wss://example.invalid")
    monkeypatch.setenv("SURREAL_NS", "ns")
    monkeypatch.setenv("SURREAL_DB", "db")
    monkeypatch.setenv("SURREAL_USER", "alice")
    monkeypatch.setenv("SURREAL_PASS", "hunter2-secret")

    class Boom:
        async def __aenter__(self):
            raise RuntimeError("bad creds alice hunter2-secret")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(db, "AsyncSurreal", lambda url: Boom())
    with caplog.at_level("WARNING"):
        assert asyncio.run(db.ping()) is False
    assert "RuntimeError" in caplog.text
    assert "hunter2-secret" not in caplog.text
    assert "alice" not in caplog.text


def test_cors_allows_configured_web_origin(client):
    origin = get_settings().web_origins[0]
    resp = client.get("/health", headers={"Origin": origin})
    assert resp.headers.get("access-control-allow-origin") == origin


def test_cors_rejects_unknown_origin(client):
    resp = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.parametrize(
    ("level", "expected_keys"),
    [
        ("root", {"username", "password"}),
        ("namespace", {"username", "password", "namespace"}),
        ("database", {"username", "password", "namespace", "database"}),
    ],
)
def test_signin_payload_matches_auth_level(monkeypatch, level, expected_keys):
    monkeypatch.setenv("SURREAL_USER", "u")
    monkeypatch.setenv("SURREAL_PASS", "p")
    monkeypatch.setenv("SURREAL_NS", "ns")
    monkeypatch.setenv("SURREAL_DB", "d")
    monkeypatch.setenv("SURREAL_AUTH_LEVEL", level)
    assert set(db._signin_vars(get_settings())) == expected_keys
