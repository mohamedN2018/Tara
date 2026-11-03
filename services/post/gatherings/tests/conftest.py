"""Fixtures for events: a fake graph (friendships) and an event factory."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from posts.clients import Relationship


class FakeGraph:
    """Friendships as unordered pairs. ``down`` makes graph unreachable."""

    def __init__(self):
        self.pairs: set[frozenset] = set()
        self.down = False

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
    monkeypatch.setattr("gatherings.services.get_relationship", fake.relationship)
    monkeypatch.setattr("gatherings.graph.friend_ids", fake.friend_ids)
    return fake


def acct() -> str:
    return str(uuid.uuid4())


def make_event(host=None, **kw):
    from gatherings import services

    values = {
        "title": "Picnic",
        "description": "Bring food",
        "starts_at": timezone.now() + timedelta(days=3),
        "ends_at": None,
        "timezone": "Africa/Cairo",
        "location_type": "place",
        "location": "Al-Azhar Park",
        "online_url": "",
        "cover_media_id": None,
        "audience": "public",
        "capacity": None,
    }
    values.update(kw)
    return services.create_gathering(host or acct(), **values)
