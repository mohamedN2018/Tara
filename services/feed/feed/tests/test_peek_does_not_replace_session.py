"""WP 4.7 (D4): the realtime "new posts" peek never replaces the ranking session
and never calls ads. ``GET /feed/?mode=...&peek=1[&since=...]``."""

import uuid
from datetime import timedelta

import pytest
from django.core.cache import caches
from django.urls import reverse
from django.utils import timezone

from feed import ranking
from feed.models import FeedItem

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _item(viewer, author, *, minutes_ago=0, reason="follow", added_minutes_ago=None):
    post_id = str(uuid.uuid4())
    row = FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason=reason,
        snapshot={"post_id": post_id, "author_id": author, "audience": "public", "excerpt": "x"},
        post_created_at=timezone.now() - timedelta(minutes=minutes_ago),
    )
    if added_minutes_ago is not None:
        FeedItem.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timedelta(minutes=added_minutes_ago)
        )
    return row


@pytest.fixture
def ads_calls(monkeypatch):
    calls = []

    def fake(viewer):
        calls.append(viewer)
        return {"creative_id": f"c{len(calls)}", "headline": "Ad", "sponsored": True}

    monkeypatch.setattr("feed.ads_client.feed_sponsored", fake)
    return calls


def _session(viewer):
    return caches["hot"].get(ranking._session_key(viewer))


def _peek(client, mode="for_you", **params):
    resp = client.get(reverse("feed:home-feed"), {"mode": mode, "peek": 1, **params})
    assert resp.status_code == 200, resp.content
    return resp.json()


def test_peek_keeps_the_session_and_its_next_page(client_for, ads_calls):
    viewer, author = _acct(), _acct()
    for m in range(12):
        _item(viewer, author, minutes_ago=m + 10, added_minutes_ago=m + 10)
    client = client_for(viewer)
    first = client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 5}).json()
    session = _session(viewer)
    assert session and first["page"]["next_cursor"]
    assert len(ads_calls) == 1  # the first page's slot

    fresh = _item(viewer, author)  # a realtime push arrives
    body = _peek(client, since=first["meta"]["as_of"])
    assert [i["post_id"] for i in body["data"]] == [str(fresh.post_id)]
    assert body["new_count"] == 1 and body["peek"] is True and body["mode"] == "for_you"
    assert "sponsored" not in body and "meta" not in body
    assert len(ads_calls) == 1  # no ads call
    assert _session(viewer) == session  # not replaced, not rewritten

    # Page 2 still reads the original session: no fallback, no repeats.
    second = client.get(
        reverse("feed:home-feed"), {"mode": "for_you", "cursor": first["page"]["next_cursor"]}
    ).json()
    assert second["page"]["fallback"] is False
    shown = {i["post_id"] for i in first["data"]}
    assert not shown & {i["post_id"] for i in second["data"]}
    assert str(fresh.post_id) not in {i["post_id"] for i in second["data"]}


def test_peek_without_a_session_creates_none(client_for, ads_calls):
    viewer = _acct()
    _item(viewer, _acct())
    _peek(client_for(viewer))
    assert _session(viewer) is None
    assert ads_calls == []


def test_peek_counts_rows_added_after_since_by_fanout_time(client_for, ads_calls):
    viewer, author = _acct(), _acct()
    client = client_for(viewer)
    since = (timezone.now() - timedelta(minutes=5)).isoformat()
    _item(viewer, author, minutes_ago=30, added_minutes_ago=30)  # before since
    late = _item(viewer, author, minutes_ago=8)  # written before since, fanned out after
    new = [_item(viewer, author, minutes_ago=m) for m in (1, 2)]
    body = _peek(client, mode="recent", since=since, limit=2)
    assert [i["post_id"] for i in body["data"]] == [str(r.post_id) for r in new]
    assert body["new_count"] == 3  # the page holds 2, the count is all of them
    assert str(late.post_id) in {
        i["post_id"] for i in _peek(client, mode="recent", since=since)["data"]
    }


@pytest.mark.parametrize("mode", ["recent", "following", "friends", "favorites", "for_you"])
def test_peek_respects_the_mode_and_hides(client_for, ads_calls, mode):
    viewer, friend = _acct(), _acct()
    friend_row = _item(viewer, friend, reason="friend")
    hidden = _item(viewer, friend, reason="friend")
    client = client_for(viewer)
    client.post(reverse("feed:hide"), {"post_id": str(hidden.post_id), "reason": "spam"})
    ids = [i["post_id"] for i in _peek(client, mode=mode)["data"]]
    assert str(hidden.post_id) not in ids
    if mode in ("recent", "friends", "for_you"):
        assert ids == [str(friend_row.post_id)]
    else:  # not followed and not a favorite
        assert ids == []
    assert ads_calls == []


def test_peek_items_carry_serve_tokens(client_for, ads_calls):
    viewer = _acct()
    _item(viewer, _acct())
    body = _peek(client_for(viewer))
    assert body["data"][0]["st"]


def test_peek_rejects_a_bad_since(client_for, ads_calls):
    resp = client_for(_acct()).get(reverse("feed:home-feed"), {"peek": 1, "since": "yesterday"})
    assert resp.status_code == 400


def test_since_is_clamped_to_the_config_window(client_for, ads_calls):
    viewer = _acct()
    old = _item(viewer, _acct(), minutes_ago=60 * 24 * 8, added_minutes_ago=60 * 24 * 8)
    body = _peek(client_for(viewer), mode="recent", since="0")
    assert str(old.post_id) not in [i["post_id"] for i in body["data"]]
