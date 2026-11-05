"""Fixtures for reels: a fake graph (friends, follows, mutes) and transcoded videos."""

import uuid

import pytest
from posts.clients import Relationship


class FakeGraph:
    """Friendships as unordered pairs, follows as (follower, target). ``down``
    makes graph unreachable (friends and follows unknown, mutes unknown)."""

    def __init__(self):
        self.pairs: set[frozenset] = set()
        self.follows: set[tuple[str, str]] = set()
        self.mutes: set[tuple[str, str]] = set()
        self.blocks: set[frozenset] = set()
        self.down = False

    def befriend(self, a, b) -> None:
        self.pairs.add(frozenset({str(a), str(b)}))

    def follow(self, follower, target) -> None:
        self.follows.add((str(follower), str(target)))

    def mute(self, owner, target) -> None:
        self.mutes.add((str(owner), str(target)))

    def relationship(self, a, b) -> Relationship:
        if self.down:
            return Relationship.unknown()
        a, b = str(a), str(b)
        return Relationship(
            are_friends=frozenset({a, b}) in self.pairs,
            a_follows_b=(a, b) in self.follows,
            blocked_either_way=frozenset({a, b}) in self.blocks,
        )

    def friend_ids(self, account_id):
        if self.down:
            return None
        me = str(account_id)
        return {next(iter(p - {me})) for p in self.pairs if me in p}

    def relations(self, viewer, users, pages):
        if self.down:
            return None
        viewer = str(viewer)
        out = {}
        for u in users:
            if frozenset({viewer, str(u)}) in self.blocks:
                continue
            friends = frozenset({viewer, str(u)}) in self.pairs
            out[str(u)] = {
                "state": "friends" if friends else "none",
                "following": (viewer, str(u)) in self.follows,
            }
        for p in pages:
            out[str(p)] = {"following": (viewer, str(p)) in self.follows}
        return out

    def muted_ids(self, viewer):
        if self.down:
            return set()
        return {t for o, t in self.mutes if o == str(viewer)}


@pytest.fixture(autouse=True)
def graph(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr("posts.services.get_relationship", fake.relationship)
    monkeypatch.setattr("gatherings.graph.friend_ids", fake.friend_ids)
    monkeypatch.setattr("reels.services._relations", fake.relations)
    monkeypatch.setattr("reels.services.muted_ids", fake.muted_ids)
    return fake


def acct() -> str:
    return str(uuid.uuid4())


def add_video(
    media_stub, owner, *, width=720, height=1280, duration_ms=15_000, status="ready", purpose="post"
) -> str:
    """A video as media's internal lookup reports it after transcoding."""
    from posts.media_client import MediaInfo

    media_id = str(uuid.uuid4())
    media_stub.assets[media_id] = MediaInfo(
        media_id,
        str(owner),
        "video",
        status,
        purpose,
        duration_ms=duration_ms,
        width=width,
        height=height,
    )
    return media_id
