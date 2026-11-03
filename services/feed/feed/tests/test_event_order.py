"""Retries reorder events: the feed keeps the newest edit or delete per post
(roadmap 3.3, "Read models and event order")."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from feed import handlers
from feed.models import FeedItem, PostState
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _event(event_type: str, payload: dict, at) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        subject_id=payload["post_id"],
        producer="post-service",
        payload=payload,
        occurred_at=at.isoformat(),
    )


@pytest.fixture
def world(monkeypatch):
    """An author with one follower and one friend; ``t`` is the post's creation."""
    author, follower, friend = _acct(), _acct(), _acct()
    monkeypatch.setattr(
        "feed.services.fanout_audience",
        lambda a: {"followers": [follower], "friends": [friend], "recipients": []},
    )
    t = timezone.now() - timedelta(minutes=10)
    created = {
        "post_id": str(uuid.uuid4()),
        "author_id": author,
        "type": "text",
        "audience": "public",
        "excerpt": "secret plans",
        "media_ids": [],
        "created_at": t.isoformat(),
    }
    return author, follower, friend, created, t


def _rows(post_id: str) -> dict[str, dict]:
    return {str(i.recipient_id): i.snapshot for i in FeedItem.objects.filter(post_id=post_id)}


def test_a_post_created_retried_after_the_delete_fans_out_nothing(world):
    _, _, _, created, t = world
    handlers.on_post_deleted(
        _event("post.deleted", {"post_id": created["post_id"]}, t + timedelta(seconds=5))
    )
    handlers.on_post_created(_event("post.created", created, t))
    assert _rows(created["post_id"]) == {}
    assert PostState.objects.get(post_id=created["post_id"]).deleted is True


def test_a_post_created_retried_after_a_narrowing_edit_uses_the_edit(world):
    author, follower, friend, created, t = world
    edit = {**created, "audience": "only_me", "excerpt": "nothing to see"}
    handlers.on_post_updated(_event("post.updated", edit, t + timedelta(seconds=5)))
    handlers.on_post_created(_event("post.created", created, t))
    rows = _rows(created["post_id"])
    assert set(rows) == {author}
    assert rows[author]["excerpt"] == "nothing to see"
    assert rows[author]["audience"] == "only_me"


def test_an_edit_older_than_the_stored_one_changes_nothing(world):
    _, follower, friend, created, t = world
    handlers.on_post_created(_event("post.created", created, t))
    narrow = {**created, "audience": "friends", "excerpt": "friends only now"}
    handlers.on_post_updated(_event("post.updated", narrow, t + timedelta(seconds=10)))
    stale = {**created, "audience": "public", "excerpt": "old public text"}
    handlers.on_post_updated(_event("post.updated", stale, t + timedelta(seconds=5)))

    rows = _rows(created["post_id"])
    assert follower not in rows
    assert rows[friend]["audience"] == "friends"
    assert "excerpt" not in rows[friend]


def test_an_edit_newer_than_a_removal_brings_the_post_back_to_life(world):
    # Moderation: remove (post.deleted), then an overturned appeal (post.updated).
    author, _, _, created, t = world
    handlers.on_post_deleted(
        _event("post.deleted", {"post_id": created["post_id"]}, t + timedelta(seconds=5))
    )
    handlers.on_post_updated(_event("post.updated", created, t + timedelta(seconds=10)))
    handlers.on_post_created(_event("post.created", created, t))  # a late retry
    assert author in _rows(created["post_id"])
