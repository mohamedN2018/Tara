"""Pytest config for the Chat service (mint RS256 tokens; stub external infra)."""

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


@pytest.fixture
def client_for():
    from rest_framework.test import APIClient

    def _make(account_id: str):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(account_id)}")
        return c

    return _make


class FakeMedia:
    """Stands in for media's internal API: only registered uploads exist."""

    def __init__(self) -> None:
        import uuid

        self._uuid = uuid
        self.assets: dict[str, dict] = {}
        self.down = False

    def add(
        self,
        owner_id: str,
        kind: str = "image",
        *,
        status: str = "ready",
        visibility: str = "private",
        size: int = 1000,
        mime: str = "",
    ) -> str:
        media_id = str(self._uuid.uuid4())
        self.assets[media_id] = {
            "id": media_id,
            "owner_id": str(owner_id),
            "kind": kind,
            "status": status,
            "mime": mime or {"image": "image/jpeg", "video": "video/mp4"}.get(kind, "audio/ogg"),
            "bytes": size,
            "visibility": visibility,
        }
        return media_id

    def lookup(self, media_ids):
        from chat.media_client import MediaInfo

        if self.down:
            from chat.media_client import _unavailable

            raise _unavailable()
        return {m: MediaInfo(**self.assets[m]) for m in map(str, media_ids) if m in self.assets}

    def signed(self, media_id):
        from chat.media_client import MediaNotFound, _unavailable

        if self.down:
            raise _unavailable()
        asset = self.assets.get(str(media_id))
        if asset is None:
            raise MediaNotFound(media_id)
        return {
            **asset,
            "url": f"https://storage.test/{media_id}?signed=1",
            "variants": [{"kind": "thumb", "url": f"https://storage.test/{media_id}/thumb"}],
        }


@pytest.fixture(autouse=True)
def media(monkeypatch):
    fake = FakeMedia()
    monkeypatch.setattr("chat.media_client.lookup", fake.lookup)
    monkeypatch.setattr("chat.media_client.signed", fake.signed)
    return fake
