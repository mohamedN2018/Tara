"""R3 WP A5 (07 WP 4b.7, 06 sections 6.2 and 6.3): ``GET /feed/?peek=1&since=``.

The pill counts **only eligible rows** (a raw ``FeedItem`` count leaked how many posts
hidden, blocked or restricted authors made): ``new_count`` equals the number of rows
the same mode's page would show, capped at ``peek.max_count`` with
``new_count_capped``; ``since`` is clamped to ``session.new_since.max_age_h`` and
echoed; the ranking session and the ads are never touched."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import caches
from feed import ranking
from feed.models import FeedItem

from intel.models import ContentRef
from intel.tests import world as w

pytestmark = pytest.mark.django_db


ADS_CALLS: list = []


@pytest.fixture(autouse=True)
def _no_ads(monkeypatch):
    ADS_CALLS.clear()
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: ADS_CALLS.append(v))


def _row(viewer, author, at, *, content=True, state="live"):
    post_id = str(uuid.uuid4())
    if content:
        ContentRef.objects.create(
            post_id=post_id,
            author_id=author,
            author_type="user",
            type="text",
            audience="public",
            state=state,
            created_at=at,
            event_at=at,
        )
    return FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason="friend",
        snapshot={"post_id": post_id, "author_id": author, "type": "text"},
        post_created_at=at,
    )


def _peek(client, mode, since, **extra):
    calls = len(ADS_CALLS)
    resp = client.get("/api/v1/feed/", {"mode": mode, "peek": "1", "since": since, **extra})
    assert resp.status_code == 200
    assert len(ADS_CALLS) == calls  # a peek never calls ads
    return resp.json()


@pytest.mark.parametrize("mode", ["for_you", "recent"])
def test_new_count_is_the_eligible_count(client_for, mode):
    viewer, friend, foe, gone = w.uid(), w.uid(), w.uid(), w.uid()
    since = datetime.now(UTC) - timedelta(minutes=5)
    good = [_row(viewer, friend, since + timedelta(seconds=10 + i)) for i in range(3)]
    w.block(viewer, foe)
    blocked = _row(viewer, foe, since + timedelta(seconds=30))  # a fan-out racing the block
    deleted = _row(viewer, gone, since + timedelta(seconds=40), state="deleted")
    body = _peek(client_for(viewer), mode, since.isoformat())
    assert body["peek"] is True and body["mode"] == mode
    ids = body["ids"]
    assert str(blocked.post_id) not in ids
    assert {str(r.post_id) for r in good} <= set(ids)
    if mode == "for_you":
        # E1: the content read model says deleted; the ranked mode never shows it.
        assert str(deleted.post_id) not in ids
        assert body["new_count"] == 3
    else:
        # The chronological page shows feed rows (post.deleted removes them): the
        # count is the page's own rows, never more.
        assert body["new_count"] == len(ids) == 4
    assert body["new_count_capped"] is False
    assert [i["post_id"] for i in body["data"]] == ids


def test_a_blocked_authors_post_is_invisible_to_peek(client_for):
    viewer, friend, foe = w.uid(), w.uid(), w.uid()
    since = datetime.now(UTC) - timedelta(minutes=5)
    _row(viewer, friend, since + timedelta(seconds=10))
    client = client_for(viewer)
    before = _peek(client, "for_you", since.isoformat())
    w.block(foe, viewer)  # either way
    _row(viewer, foe, since + timedelta(seconds=20))
    after = _peek(client, "for_you", since.isoformat())
    assert after["new_count"] == before["new_count"] == 1
    assert after["ids"] == before["ids"]


def test_since_is_clamped_and_echoed(client_for):
    viewer, friend = w.uid(), w.uid()
    old = datetime.now(UTC) - timedelta(days=30)
    _row(viewer, friend, datetime.now(UTC) - timedelta(days=10))  # past max_age_h (7 d)
    _row(viewer, friend, datetime.now(UTC) - timedelta(hours=1))
    body = _peek(client_for(viewer), "recent", old.isoformat())
    echoed = datetime.fromisoformat(body["since"])
    assert abs((datetime.now(UTC) - timedelta(hours=168) - echoed).total_seconds()) < 60
    assert body["new_count"] == 1


def test_the_count_is_capped_at_peek_max_count(client_for):
    viewer, friend = w.uid(), w.uid()
    since = datetime.now(UTC) - timedelta(hours=1)
    FeedItem.objects.bulk_create(
        [
            FeedItem(
                recipient_id=viewer,
                post_id=uuid.uuid4(),
                author_id=friend,
                reason="friend",
                snapshot={"type": "text"},
                post_created_at=since + timedelta(seconds=i + 1),
            )
            for i in range(105)
        ]
    )
    body = _peek(client_for(viewer), "recent", since.isoformat(), limit=5)
    assert body["new_count"] == 99 and body["new_count_capped"] is True
    assert len(body["data"]) == 5


def test_peek_never_replaces_the_ranking_session(client_for):
    viewer, friend = w.uid(), w.uid()
    for i in range(5):
        _row(viewer, friend, datetime.now(UTC) - timedelta(minutes=10 + i))
    client = client_for(viewer)
    client.get("/api/v1/feed/", {"mode": "for_you"})
    session = caches["hot"].get(ranking._session_key(viewer))
    _peek(client, "for_you", (datetime.now(UTC) - timedelta(hours=1)).isoformat())
    assert caches["hot"].get(ranking._session_key(viewer)) == session
