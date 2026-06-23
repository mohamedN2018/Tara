"""BFF tests: health probe + auth gating + uniform error envelope."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_ok():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_whoami_requires_bearer():
    resp = client.get("/bff/v1/whoami")
    assert resp.status_code == 401
    body = resp.json()
    # Same error envelope shape as the Django services.
    assert body["error"]["code"] == "unauthenticated"
    assert "request_id" in body["error"]


def test_whoami_rejects_garbage_token():
    resp = client.get("/bff/v1/whoami", headers={"Authorization": "Bearer not-a-jwt"})
    # 401 (invalid) or 503 (cannot reach JWKS in unit env) — never 200.
    assert resp.status_code in (401, 503)
