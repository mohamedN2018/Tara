"""Pytest config for the Feed service (mint RS256 tokens; stub external infra)."""

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
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "hot": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "feed-hot-tests",
        },
    }
    from django.core.cache import caches

    caches["hot"].clear()
    # Tara Intelligence: production defaults unless a test opts in; per-process
    # caches never carry state from one test's (rolled-back) transaction to the next.
    settings.TARA_ENV = "development"
    settings.INTEL_ACCEPT_SYNTHETIC = False
    settings.INTEL_SYNTHETIC_IN_RANKING = False
    settings.INTEL_SIGNAL_RETENTION_DAYS = 30
    settings.INTEL_ENGAGEMENT_RETENTION_DAYS = 30
    settings.INTEL_SERVE_TOKEN_SECRET = "test-intel-serve-token-secret-0123456789abcdef"
    from intel import origin
    from intel.signals import partitions

    origin.clear_cache()
    partitions.forget_known()
    return settings


def make_access_token(account_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(account_id),
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
def client_for():
    from rest_framework.test import APIClient

    def _make(account_id: str):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(account_id)}")
        return c

    return _make
