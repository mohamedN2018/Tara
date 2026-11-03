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


def _token_with_kid() -> str:
    import jwt

    return jwt.encode({"sub": "x"}, "secret", algorithm="HS256", headers={"kid": "nope"})


class _Keys:
    def __init__(self, exc):
        self.exc = exc

    def get_signing_key_from_jwt(self, token):
        raise self.exc


def test_unknown_signing_key_is_401_but_unreachable_jwks_is_503(monkeypatch):
    import jwt

    from app import auth

    monkeypatch.setattr(
        auth, "_jwk_client", lambda: _Keys(jwt.PyJWKClientError("Unable to find a signing key"))
    )
    resp = client.get("/bff/v1/whoami", headers={"Authorization": f"Bearer {_token_with_kid()}"})
    assert resp.status_code == 401

    monkeypatch.setattr(
        auth, "_jwk_client", lambda: _Keys(jwt.PyJWKClientConnectionError("Fail to fetch data"))
    )
    resp = client.get("/bff/v1/whoami", headers={"Authorization": f"Bearer {_token_with_kid()}"})
    assert resp.status_code == 503


def test_jwks_fetch_is_bounded_by_the_upstream_timeout(monkeypatch):
    from app import auth
    from app.config import settings

    monkeypatch.setattr(auth, "_client", None)
    assert auth._jwk_client().timeout == settings.upstream_timeout_seconds
