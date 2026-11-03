"""Pytest config for the Ads service (mint RS256 tokens with roles)."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = (
    _key.public_key()
    .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    .decode()
)


@pytest.fixture(autouse=True)
def _isolated_settings(settings):
    settings.TARA_JWT_PUBLIC_KEY = _PUBLIC_PEM
    settings.TARA_JWKS_URL = ""
    settings.TARA_JWT_ISSUER = "tara-identity"
    settings.TARA_JWT_AUDIENCE = "tara"
    settings.TARA_EVENT_PUBLISHER = "null"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.ADS_AUTO_APPROVE = True
    # Pinned so the suite never depends on the host's TARA_ENV or .env.
    settings.TARA_ENV = "development"
    settings.ADS_SERVING_ENABLED = True
    settings.ADS_SERVE_TOKEN_SECRET = "test-ads-serve-token-secret-0123456789abcdef"
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    return settings


def make_access_token(
    account_id: str, roles: list[str] | None = None, caps: list[str] | None = None
) -> str:
    """``caps=None`` leaves the claim out, like a token minted before 8.12."""
    now = int(time.time())
    claims = {
        "sub": str(account_id),
        "type": "access",
        "scope": "user",
        "roles": roles or [],
        "iss": "tara-identity",
        "aud": "tara",
        "iat": now,
        "exp": now + 900,
    }
    if caps is not None:
        claims["caps"] = caps
    return jwt.encode(
        claims,
        _PRIVATE_PEM,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


@pytest.fixture
def client_for():
    from rest_framework.test import APIClient

    def _make(account_id: str, roles: list[str] | None = None, caps: list[str] | None = None):
        c = APIClient()
        token = make_access_token(account_id, roles, caps)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return c

    return _make
