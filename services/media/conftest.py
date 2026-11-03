"""Pytest config for the Media service (fake storage; mint RS256 tokens locally)."""

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
    settings.STORAGE_BACKEND = "fake"
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    return settings


@pytest.fixture(autouse=True)
def _fresh_post_breaker(monkeypatch):
    from media_app import post_client

    from tara_resilience import CircuitBreaker

    monkeypatch.setattr(post_client, "_breaker", CircuitBreaker(name="post-test"))


@pytest.fixture
def memory_storage(settings):
    """A bucket in a dict: the real verify, copy and image-cleaning paths run."""
    from media_app import storage

    settings.STORAGE_BACKEND = "memory"
    storage.memory_reset()
    yield storage
    storage.memory_reset()


@pytest.fixture
def post_visibility(monkeypatch):
    """Stub post's internal visibility answer: ``post_visibility.allow(viewer, post)``."""
    from media_app import post_client

    class _Visibility:
        def __init__(self):
            self.allowed: set[tuple[str, str]] = set()
            self.calls: list[tuple[str, str]] = []

        def allow(self, viewer_id, post_id):
            self.allowed.add((str(viewer_id), str(post_id)))

        def revoke(self, viewer_id, post_id):
            self.allowed.discard((str(viewer_id), str(post_id)))

        def __call__(self, viewer_id, post_id):
            self.calls.append((str(viewer_id), str(post_id)))
            return (str(viewer_id), str(post_id)) in self.allowed

    stub = _Visibility()
    monkeypatch.setattr(post_client, "can_view_post", stub)
    return stub


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
