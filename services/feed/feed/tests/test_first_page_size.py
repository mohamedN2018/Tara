"""WP 4c.2-B3 (08 section 7.2): page sizes come from ``delivery`` in the Home config.

- no cursor, no ``limit``: ``delivery.first_page_size`` (10);
- a cursor, no ``limit``: ``delivery.page_size`` (20);
- ``limit`` is still honoured, capped at 100.
In the chronological modes and in ``for_you`` (the ranked session is still built
over every candidate; only the count returned changes). Every non-peek page carries
``meta.delivery`` exactly as validated; ``entry`` is validated and changes nothing.
"""

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from intel import config
from intel.config import store

from feed import ranking
from feed.models import FeedItem, FollowEdge, RelationshipFlag

pytestmark = pytest.mark.django_db
MODES = ("recent", "following", "friends", "favorites", "for_you")


@pytest.fixture(autouse=True)
def no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


def _acct() -> str:
    return str(uuid.uuid4())


def _row(viewer, author, minutes_ago, reason):
    post_id = str(uuid.uuid4())
    return FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason=reason,
        snapshot={"post_id": post_id, "author_id": author, "audience": "public", "excerpt": "x"},
        post_created_at=timezone.now() - timedelta(minutes=minutes_ago),
    )


@pytest.fixture
def viewer():
    """45 friend rows (spread over 15 friends) and 45 rows of a followed favorite."""
    me, fav = _acct(), _acct()
    friends = [_acct() for _ in range(15)]
    for i in range(45):
        _row(me, friends[i % 15], i * 2, "friend")
        _row(me, fav, i * 2 + 1, "follow")
    now = timezone.now()
    FollowEdge.objects.create(follower_id=me, target_id=fav, occurred_at=now)
    RelationshipFlag.objects.create(actor_id=me, target_id=fav, kind="favorite", occurred_at=now)
    return me


def _get(client, **params):
    resp = client.get(reverse("feed:home-feed"), params)
    assert resp.status_code == 200, resp.content
    return resp.json()


@pytest.mark.parametrize("mode", MODES)
def test_page_sizes_follow_the_delivery_block(client_for, viewer, mode):
    client = client_for(viewer)
    delivery = config.delivery_for("home")
    assert (delivery["first_page_size"], delivery["page_size"]) == (10, 20)
    first = _get(client, mode=mode)
    assert len(first["data"]) == 10
    assert first["page"]["has_more"] is True
    later = _get(client, mode=mode, cursor=first["page"]["next_cursor"])
    assert len(later["data"]) == 20
    assert len(_get(client, mode=mode, limit=20)["data"]) == 20
    with_limit = _get(client, mode=mode, cursor=first["page"]["next_cursor"], limit=7)
    assert len(with_limit["data"]) == 7


@pytest.mark.parametrize("mode", ("recent", "for_you"))
def test_limit_is_capped_at_100_and_garbage_falls_back(client_for, mode):
    me, author = _acct(), _acct()
    for i in range(110):
        _row(me, author if i % 2 else _acct(), i, "friend")
    client = client_for(me)
    assert len(_get(client, mode=mode, limit=500)["data"]) == 100
    assert len(_get(client, mode=mode, limit="many")["data"]) == 10
    assert len(_get(client, mode=mode, limit=0)["data"]) == 1


def test_the_sizes_are_read_from_the_config(client_for, viewer, monkeypatch):
    version, params = store.resolve("home")
    changed = {**params, "delivery": {**params["delivery"], "first_page_size": 4, "page_size": 6}}
    real = store.resolve
    monkeypatch.setattr(store, "resolve", lambda s: (version, changed) if s == "home" else real(s))
    client = client_for(viewer)
    for mode in ("recent", "for_you"):
        first = _get(client, mode=mode)
        assert len(first["data"]) == 4
        assert len(_get(client, mode=mode, cursor=first["page"]["next_cursor"])["data"]) == 6
        assert first["meta"]["delivery"]["first_page_size"] == 4


def test_the_ranked_session_still_holds_every_candidate(client_for, viewer):
    from intel.ranking import session as rank_session

    first = _get(client_for(viewer), mode="for_you")
    assert len(first["data"]) == 10
    stored = ranking._hot().get(rank_session.key(ranking.SURFACE, viewer))
    assert stored is not None and stored["n"] == 90


@pytest.mark.parametrize("mode", MODES)
def test_every_page_carries_meta_delivery_and_keeps_the_rest_of_meta(client_for, viewer, mode):
    client = client_for(viewer)
    block = config.delivery_for("home")
    first = _get(client, mode=mode)
    assert first["meta"]["delivery"] == block
    later = _get(client, mode=mode, cursor=first["page"]["next_cursor"])
    assert later["meta"]["delivery"] == block
    if mode == "for_you":
        assert "caught_up_index" in first["meta"] and "caught_up_index" in later["meta"]
    assert {"ad_slots", "as_of"} <= set(first["meta"])  # first page only, as before
    assert "ad_slots" not in later["meta"]


def test_peek_keeps_its_behaviour(client_for, viewer):
    client = client_for(viewer)
    since = (timezone.now() - timedelta(hours=3)).isoformat()
    body = _get(client, mode="recent", peek=1, since=since)
    assert body["peek"] is True and "meta" not in body
    assert len(body["data"]) == 20  # today's default, not first_page_size
    assert body["new_count"] == 90


def test_entry_is_validated_and_changes_nothing(client_for, viewer):
    client = client_for(viewer)
    plain = [i["post_id"] for i in _get(client, mode="recent")["data"]]
    for entry in ("open", "reload", "refresh", "return"):
        assert [i["post_id"] for i in _get(client, mode="recent", entry=entry)["data"]] == plain
    for bad in ("", "Open", "scroll"):
        resp = client.get(reverse("feed:home-feed"), {"mode": "recent", "entry": bad})
        assert resp.status_code == 400, bad
        assert [d["field"] for d in resp.json()["error"]["details"]] == ["entry"]
