"""Pytest config for the Profile service.

Generates an RS256 keypair; the service verifies access tokens against the
public key (TARA_JWT_PUBLIC_KEY) and tests mint tokens with the private key — so
no running Identity/JWKS endpoint is needed. External infra is stubbed.
"""

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
    settings.TARA_JWKS_URL = ""  # force static-PEM verification path
    settings.TARA_JWT_ISSUER = "tara-identity"
    settings.TARA_JWT_AUDIENCE = "tara"
    settings.TARA_EVENT_PUBLISHER = "null"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    return settings


def make_access_token(account_id: str, *, email: str = "u@tara.local") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(account_id),
            "email": email,
            "type": "access",
            "scope": "user",
            "iss": "tara-identity",
            "aud": "tara",
            "iat": now,
            "exp": now + 900,
        },
        _PRIVATE_PEM,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def auth_client(api_client):
    def _make(account_id: str):
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(account_id)}")
        return api_client

    return _make
