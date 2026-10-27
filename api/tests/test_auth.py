"""Phase 7 'Done when': a logged-out API call is 401, and a run created in org A is 404 for a
token from org B. Tokens are real RS256 JWTs signed with a throwaway key; only the fetch of
Clerk's public key is replaced, so signature, expiry, issuer and azp checks all really run."""

import asyncio
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from test_fork import record
from test_renewal_brief import APPROVE, BUGGY_PLAN, draft

ISSUER = "https://clerk.test"
ORIGIN = "http://localhost:3000"

_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(claims=None, key=_PRIVATE, algorithm="RS256", v1_org=True, **drop):
    """A session token. By default it carries the v1 org claims; v1_org=False omits them."""
    now = int(time.time())
    body = {"iss": ISSUER, "sub": "user_1", "iat": now, "exp": now + 60, "azp": ORIGIN,
            **({"org_id": "org_A", "org_role": "org:admin"} if v1_org else {}), **(claims or {})}
    for name in drop:
        body.pop(name)
    return jwt.encode(body, key, algorithm=algorithm, headers={"kid": "test-key"})


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(autouse=True)
def clerk(monkeypatch):
    monkeypatch.setenv("CLERK_ISSUER", ISSUER)
    monkeypatch.setenv("CLERK_JWKS_URL", f"{ISSUER}/.well-known/jwks.json")
    monkeypatch.setenv("WEB_ORIGINS", ORIGIN)
    monkeypatch.setattr(auth, "_signing_key", lambda t: _PRIVATE.public_key())  # no network


@pytest.fixture
def client(store):
    return TestClient(app)


def principal(t):
    return asyncio.run(auth.get_principal(f"Bearer {t}"))


# --- the two Done-when criteria --------------------------------------------------------------

def test_a_logged_out_call_is_401(client):
    resp = client.get("/v1/runs")
    assert resp.status_code == 401 and resp.headers["www-authenticate"] == "Bearer"


def test_a_run_created_in_org_a_is_404_for_a_token_from_org_b(client, store):
    parent = record(BUGGY_PLAN, "s", draft(0), APPROVE, ws="org_A")
    org_a, org_b = bearer(token({"org_id": "org_A"})), bearer(token({"org_id": "org_B", "sub": "user_2"}))

    assert client.get(f"/v1/runs/{parent}", headers=org_a).status_code == 200
    assert client.get(f"/v1/runs/{parent}", headers=org_b).status_code == 404
    assert [r["id"] for r in client.get("/v1/runs", headers=org_a).json()] == [parent]
    assert client.get("/v1/runs", headers=org_b).json() == []


# --- what a valid token yields ---------------------------------------------------------------

def test_workspace_and_role_come_from_the_verified_token_v1_claims():
    p = principal(token({"org_id": "org_X", "org_role": "org:admin"}))
    assert (p.user_id, p.org_id, p.org_role, p.is_admin) == ("user_1", "org_X", "admin", True)
    assert principal(token({"org_role": "org:member"})).is_admin is False


def test_the_nested_v2_claim_layout_is_accepted_too():
    p = principal(token({"o": {"id": "org_V2", "rol": "admin"}}, v1_org=False))
    assert (p.org_id, p.org_role) == ("org_V2", "admin")


def test_a_token_without_an_azp_claim_is_allowed():
    assert principal(token(azp=None)).org_id == "org_A"


# --- tokens that must be refused -------------------------------------------------------------

def refused(t, status=401):
    with pytest.raises(HTTPException) as err:
        principal(t)
    assert err.value.status_code == status


def test_expired_wrong_issuer_and_missing_claims_are_401():
    refused(token({"exp": int(time.time()) - 3600}))
    refused(token({"iss": "https://evil.example"}))
    refused(token(exp=None))
    refused(token(sub=None))


def test_forged_and_tampered_tokens_are_401():
    refused(token(key=_OTHER))  # signed with someone else's key
    refused(token(None, key=None, algorithm="none"))  # unsigned
    refused(token(None, key="shared-secret-shared-secret-1234", algorithm="HS256"))  # alg confusion
    good = token()
    refused(good[:-4] + ("AAAA" if not good.endswith("AAAA") else "BBBB"))  # flipped signature
    refused("not.a.jwt")


def test_a_token_issued_to_another_origin_is_401():
    refused(token({"azp": "https://evil.example"}))


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer ", "Basic abc", "token-without-scheme"])
def test_missing_or_malformed_authorization_headers_are_401(header):
    with pytest.raises(HTTPException) as err:
        asyncio.run(auth.get_principal(header))
    assert err.value.status_code == 401


def test_a_signed_in_user_with_no_active_organization_gets_a_clear_403(client):
    t = token(org_id=None, org_role=None)
    assert client.get("/v1/runs", headers=bearer(t)).status_code == 403
    assert "organization" in client.get("/v1/runs", headers=bearer(t)).json()["detail"].lower()


# --- configuration and outages ---------------------------------------------------------------

def test_auth_is_503_not_silently_open_when_clerk_is_not_configured(monkeypatch):
    monkeypatch.setenv("CLERK_ISSUER", "")
    refused(token(), status=503)


def test_an_unreachable_key_server_is_503(monkeypatch):
    def down(_t):
        raise jwt.PyJWKClientConnectionError("boom")

    monkeypatch.setattr(auth, "_signing_key", down)
    refused(token(), status=503)


# --- the two auth schemes do not mix ---------------------------------------------------------

def test_a_clerk_token_is_not_an_ingest_key_and_an_ingest_key_is_not_a_clerk_token(client):
    assert client.post("/v1/runs", headers=bearer(token()),
                       json={"id": "run0000000000001", "workflow": "w", "started_at": "t"}).status_code == 401
    assert client.get("/v1/runs", headers=bearer("at_live_" + "x" * 30)).status_code == 401
