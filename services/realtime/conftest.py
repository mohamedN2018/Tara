"""Pytest config for the Realtime gateway: in-memory channel layer + RS256 tokens."""

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
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    return settings


def make_access_token(account_id: str, **claims) -> str:
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
            **claims,
        },
        _PRIVATE_PEM,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


@pytest.fixture
def token_for():
    return make_access_token


@pytest.fixture(autouse=True)
def _everyone_is_a_member(monkeypatch):
    monkeypatch.setattr("realtime.chat_client.is_member", lambda conversation, account: True)


@pytest.fixture(autouse=True)
def _memory_presence(settings):
    """In-process presence store, fresh for every test."""
    from realtime import presence

    settings.PRESENCE_BACKEND = "memory"
    presence.reset_store()
    yield
    presence.reset_store()


@pytest.fixture(autouse=True)
def audiences(monkeypatch):
    """``audiences[account] = {peers}``; anyone not listed has no peers."""
    table: dict[str, set[str]] = {}
    monkeypatch.setattr(
        "realtime.peers.audience", lambda account_id: set(table.get(str(account_id), set()))
    )
    return table
