"""Pytest config for the Post service (mint RS256 tokens; stub external infra)."""

import time
import uuid

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
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
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


class FakeMedia:
    """Stands in for the media service's internal API.

    Only media registered with ``add`` exist, as in the real service, so a test
    that attaches media must say who owns it.
    """

    def __init__(self):
        from posts.media_client import MediaInfo

        self._info = MediaInfo
        self.assets: dict = {}
        self.binds: list[dict] = []
        self.calls: list[str] = []
        self.elsewhere: set[str] = set()  # ids media says another post holds
        self.down = False

    def add(self, owner, *, kind="image", status="ready") -> str:
        media_id = str(uuid.uuid4())
        self.assets[media_id] = self._info(media_id, str(owner), kind, status)
        return media_id

    def _available(self, name: str) -> None:
        from posts import media_client

        self.calls.append(name)
        if self.down:
            raise media_client._unavailable()

    def lookup(self, media_ids):
        self._available("lookup")
        return {m: self.assets[m] for m in map(str, media_ids) if m in self.assets}

    def bind(self, owner_id, post_id, media_ids, *, restricted):
        from posts import media_client

        self._available("bind")
        ids = [str(m) for m in media_ids]
        self.binds.append(
            {
                "owner_id": str(owner_id),
                "post_id": str(post_id),
                "ids": ids,
                "restricted": restricted,
            }
        )
        owned = {m for m in ids if m in self.assets and self.assets[m].owner_id == str(owner_id)}
        skipped = [m for m in ids if m in self.elsewhere or m not in owned]
        return media_client.BindResult(
            skipped=skipped, attached_elsewhere=[m for m in ids if m in self.elsewhere]
        )


@pytest.fixture(autouse=True)
def media_stub(monkeypatch):
    from posts import media_client

    from tara_resilience import CircuitBreaker

    fake = FakeMedia()
    monkeypatch.setattr(media_client, "lookup", fake.lookup)
    monkeypatch.setattr(media_client, "bind", fake.bind)
    monkeypatch.setattr(media_client, "_breaker", CircuitBreaker(name="media-test"))
    return fake


@pytest.fixture
def client_for():
    from rest_framework.test import APIClient

    def _make(account_id: str):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(account_id)}")
        return c

    return _make
