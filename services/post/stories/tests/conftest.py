"""Fixtures for stories: a fake graph (friendships) and a story factory."""

import uuid

import pytest
from posts.clients import Relationship


class FakeGraph:
    """Friendships as unordered pairs. ``down`` makes graph unreachable."""

    def __init__(self):
        self.pairs: set[frozenset] = set()
        self.follows: set[tuple[str, str]] = set()
        self.down = False

    def follow(self, follower, target) -> None:
        self.follows.add((str(follower), str(target)))

    def followed_ids(self, viewer, candidates):
        if self.down:
            return set()
        return {c for c in candidates if (str(viewer), str(c)) in self.follows}

    def befriend(self, a, b) -> None:
        self.pairs.add(frozenset({str(a), str(b)}))

    def unfriend(self, a, b) -> None:
        self.pairs.discard(frozenset({str(a), str(b)}))

    def relationship(self, a, b) -> Relationship:
        if self.down:
            return Relationship.unknown()
        return Relationship(are_friends=frozenset({str(a), str(b)}) in self.pairs)

    def friend_ids(self, account_id):
        if self.down:
            return None
        me = str(account_id)
        return {next(iter(p - {me})) for p in self.pairs if me in p}


@pytest.fixture(autouse=True)
def graph(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr("stories.services.get_relationship", fake.relationship)
    monkeypatch.setattr("gatherings.graph.friend_ids", fake.friend_ids)
    monkeypatch.setattr("stories.services.followed_ids", fake.followed_ids)
    return fake


def acct() -> str:
    return str(uuid.uuid4())


def make_story(author=None, **kw):
    from stories import services

    values = {"kind": "text", "audience": "public", "text": "Hello", "background": "violet"}
    values.update(kw)
    return services.create_story(author or acct(), **values)
