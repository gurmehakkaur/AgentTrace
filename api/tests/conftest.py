import pytest

from app import db
from app.auth import Principal, get_principal
from app.main import app
from app.rca import memory
from app.routes import worker as worker_route
from app.security import limits
from fakes import DB_FUNCTIONS, FakeDB


@pytest.fixture
def store(monkeypatch):
    """Swap app.db's data functions for an in-memory fake."""
    fake = FakeDB()
    for name in DB_FUNCTIONS:
        monkeypatch.setattr(db, name, getattr(fake, name))
    return fake


@pytest.fixture
def login():
    """Act as a signed-in member of an organization (the workspace). Overrides get_principal;
    the real JWT verification is covered by test_auth.py. Not logged in unless called."""
    def _login(org_id: str = "ws-a", role: str = "member", user_id: str = "user_1") -> None:
        app.dependency_overrides[get_principal] = lambda: Principal(user_id, org_id, role)

    yield _login
    app.dependency_overrides.pop(get_principal, None)


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """The limiters are module-level (per process), so each test starts with empty windows."""
    limits.experiment_limiter._calls.clear()
    limits.rca_limiter._calls.clear()
    limits.key_limiter._calls.clear()
    limits.import_limiter._calls.clear()
    limits.alert_limiter._calls.clear()
    limits.key_use_limiter._calls.clear()
    worker_route._noted.clear()  # the 'worker seen' throttle is per process too
    limits.webhook_limiter._calls.clear()


@pytest.fixture(autouse=True)
def no_real_agent_memory(request, monkeypatch):
    """Offline tests must never reach the real Agent Memory service: with a key in .env, a finished
    fake experiment would otherwise write a test pattern into the real context (and slow the suite
    by seconds of network). Tests that need memory install a fake (see test_memory.py); only the
    *_live modules get the real client."""
    if not request.module.__name__.endswith("_live"):
        monkeypatch.setattr(memory, "_open", lambda: None)
