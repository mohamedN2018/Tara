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


def make_access_token(account_id: str, roles: list[str] | None = None) -> str:
    now = int(time.time())
    claims = {
        "sub": str(account_id),
        "type": "access",
        "scope": "user",
        "iss": "tara-identity",
        "aud": "tara",
        "iat": now,
        "exp": now + 900,
    }
    if roles:
        claims["roles"] = roles
    return jwt.encode(
        claims,
        _PRIVATE_PEM,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


@pytest.fixture
def client_for():
    from rest_framework.test import APIClient

    def _make(account_id: str, roles: list[str] | None = None):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(account_id, roles)}")
        return c

    return _make


class FakeMedia:
    """Stands in for media's internal API: only registered uploads exist."""

    def __init__(self) -> None:
        import uuid

        self._uuid = uuid
        self.assets: dict[str, dict] = {}
        self.down = False
        self.signed_names: list[str | None] = []  # the filename of each signed() call

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

    def signed(self, media_id, filename=None):
        from chat.media_client import MediaNotFound, _unavailable

        self.signed_names.append(filename)
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


class FakeGraph:
    """Stands in for graph's friendship lookup. Everyone is friends unless a
    test says otherwise, so a DM lands in the inbox as it did before requests."""

    def __init__(self) -> None:
        self.strangers: set[frozenset[str]] = set()
        self.mutuals: set[frozenset[str]] = set()  # strangers who share a friend
        self.down = False
        self.calls = 0

    def make_strangers(self, a: str, b: str) -> None:
        self.strangers.add(frozenset({str(a), str(b)}))

    def are_friends(self, a, b):
        self.calls += 1
        if self.down:
            return None
        return frozenset({str(a), str(b)}) not in self.strangers

    def have_mutual_friends(self, a, b):
        if self.down:
            return None
        return frozenset({str(a), str(b)}) in self.mutuals


@pytest.fixture(autouse=True)
def graph(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr("chat.graph_client.are_friends", fake.are_friends)
    monkeypatch.setattr("chat.graph_client.have_mutual_friends", fake.have_mutual_friends)
    return fake


class FakeProfile:
    """Stands in for profile's page access lookup: pages and their teams."""

    def __init__(self) -> None:
        import uuid

        self._uuid = uuid
        self.pages: dict[str, dict] = {}
        self.down = False

    def add_page(self, name="Cafe Tara", status="published", team=None) -> str:
        page_id = str(self._uuid.uuid4())
        self.pages[page_id] = {"name": name, "status": status, "team": dict(team or {})}
        return page_id

    def page_access(self, page_id, account_id):
        if self.down:
            from chat.profile_client import _unavailable

            raise _unavailable()
        page = self.pages.get(str(page_id))
        if page is None:
            return None
        return {
            "page_id": str(page_id),
            "handle": "cafe",
            "name": page["name"],
            "status": page["status"],
            "role": page["team"].get(str(account_id)),
        }

    def page_team(self, page_id):
        from chat.profile_client import PAGE_MESSAGE_ROLES

        page = self.pages.get(str(page_id))
        if self.down or page is None:
            return []  # the real client degrades the same way
        return [a for a, role in page["team"].items() if role in PAGE_MESSAGE_ROLES]


@pytest.fixture(autouse=True)
def profile(monkeypatch):
    fake = FakeProfile()
    monkeypatch.setattr("chat.profile_client.page_access", fake.page_access)
    monkeypatch.setattr("chat.profile_client.page_team", fake.page_team)
    return fake
