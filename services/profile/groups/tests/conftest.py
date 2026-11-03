"""Fixtures for groups: a fake graph (friendships), a fake media, and helpers."""

import uuid

import pytest
from profiles.media_client import MediaInfo
from profiles.models import BlockedPair

from tara_common.exceptions import TaraAPIError


class FakeGraph:
    """Friendships as unordered pairs. ``down`` makes graph unreachable."""

    def __init__(self):
        self.pairs: set[frozenset] = set()
        self.down = False

    def befriend(self, a, b) -> None:
        self.pairs.add(frozenset({str(a), str(b)}))

    def friend_ids(self, account_id):
        if self.down:
            return None
        me = str(account_id)
        return {next(iter(p - {me})) for p in self.pairs if me in p}


class FakeMedia:
    def __init__(self):
        self.assets: dict[str, MediaInfo] = {}
        self.binds: list[dict] = []
        self.down = False

    def add(self, owner, *, kind="image", status="ready") -> str:
        media_id = str(uuid.uuid4())
        self.assets[media_id] = MediaInfo(media_id, str(owner), kind, status)
        return media_id

    def lookup(self, media_ids):
        if self.down:
            raise TaraAPIError("down", code="dependency_unavailable", http_status_code=503)
        return {m: self.assets[m] for m in map(str, media_ids) if m in self.assets}

    def bind(self, owner_id, group_id, media_id):
        self.binds.append({"owner_id": owner_id, "post_id": group_id, "media_id": media_id})
        return {"bound": [media_id], "skipped": [], "attached_elsewhere": []}


@pytest.fixture(autouse=True)
def graph(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr("groups.graph.friend_ids", fake.friend_ids)
    return fake


@pytest.fixture(autouse=True)
def media(monkeypatch):
    fake = FakeMedia()
    monkeypatch.setattr("groups.media.media_client.lookup", fake.lookup)
    monkeypatch.setattr("groups.media._bind", fake.bind)
    return fake


def acct() -> str:
    return str(uuid.uuid4())


def block(blocker, blocked) -> None:
    BlockedPair.objects.create(blocker_id=blocker, blocked_id=blocked)


def make_group(owner=None, **kw):
    from groups import services

    data = {
        "name": "Cairo Cyclists",
        "handle": f"g{uuid.uuid4().hex[:12]}",
        "description": "Weekend rides",
        "category": "sports",
        "privacy": "public",
        "membership_approval": False,
        "post_approval": False,
    }
    data.update(kw)
    return services.create_group(owner or acct(), data)


def add_member(group, account=None, *, role="member", state="active"):
    """Put an account straight into the group (no events), for test set-up."""
    from django.utils import timezone

    from groups.models import GroupMember

    account = account or acct()
    GroupMember.objects.create(
        group=group,
        account_id=account,
        role=role,
        state=state,
        joined_at=timezone.now() if state == "active" else None,
    )
    if state == "active":
        group.member_count += 1
        group.save(update_fields=["member_count"])
    return account
