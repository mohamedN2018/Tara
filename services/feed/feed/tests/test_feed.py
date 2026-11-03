"""Feed fan-out + read tests (Graph audience mocked)."""

import uuid

import pytest
from django.urls import reverse
from django.utils import timezone

from feed import handlers, services
from feed.models import FeedItem, OutboxEvent

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _payload(author_id: str, audience: str = "public", post_id: str | None = None) -> dict:
    return {
        "post_id": post_id or str(uuid.uuid4()),
        "author_id": author_id,
        "author_type": "user",
        "type": "text",
        "audience": audience,
        "excerpt": "hello world",
        "media_ids": [],
        "created_at": timezone.now().isoformat(),
    }


def test_public_fanout_reaches_followers_friends_and_author(monkeypatch):
    author, follower, friend = _acct(), _acct(), _acct()
    monkeypatch.setattr(
        "feed.services.fanout_audience",
        lambda a: {"followers": [follower], "friends": [friend], "recipients": [follower, friend]},
    )
    payload = _payload(author, "public")
    created = services.fan_out_post(payload)
    assert created == 3  # follower, friend, author
    assert FeedItem.objects.filter(recipient_id=follower, post_id=payload["post_id"]).exists()
    assert FeedItem.objects.filter(recipient_id=author, reason="self").exists()
    assert OutboxEvent.objects.filter(event_type="feed.item.added").count() == 3

    # Idempotent re-delivery -> no new items.
    assert services.fan_out_post(payload) == 0


def test_only_me_fanout_skips_graph(monkeypatch):
    author = _acct()

    def _boom(_a):
        raise AssertionError("graph should not be called for only_me")

    monkeypatch.setattr("feed.services.fanout_audience", _boom)
    payload = _payload(author, "only_me")
    assert services.fan_out_post(payload) == 1
    assert FeedItem.objects.filter(recipient_id=author).count() == 1


def test_home_feed_endpoint(client_for, monkeypatch):
    author, viewer = _acct(), _acct()
    monkeypatch.setattr(
        "feed.services.fanout_audience",
        lambda a: {"followers": [viewer], "friends": [], "recipients": [viewer]},
    )
    services.fan_out_post(_payload(author, "public"))

    resp = client_for(viewer).get(reverse("feed:home-feed"))
    assert resp.status_code == 200
    body = resp.json()
    assert "page" in body
    assert len(body["data"]) == 1
    assert body["data"][0]["snapshot"]["excerpt"] == "hello world"


def test_home_feed_blends_sponsored_slot(client_for, monkeypatch):
    author, viewer = _acct(), _acct()
    monkeypatch.setattr(
        "feed.services.fanout_audience",
        lambda a: {"followers": [viewer], "friends": [], "recipients": [viewer]},
    )
    services.fan_out_post(_payload(author, "public"))
    monkeypatch.setattr(
        "feed.ads_client.feed_sponsored",
        lambda v: {"creative_id": "c1", "headline": "Sponsored", "sponsored": True},
    )
    resp = client_for(viewer).get(reverse("feed:home-feed"))
    assert resp.status_code == 200
    # 'sponsored' is a sibling of 'data'/'page' in the response envelope.
    assert resp.json()["sponsored"]["headline"] == "Sponsored"


def test_home_feed_degrades_when_ads_unavailable(client_for, monkeypatch):
    viewer = _acct()
    # Ads down -> client returns None; feed must still render (organic only).
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)
    resp = client_for(viewer).get(reverse("feed:home-feed"))
    assert resp.status_code == 200
    assert resp.json()["sponsored"] is None


def test_unfollow_removes_author_items(monkeypatch):
    author, follower = _acct(), _acct()
    monkeypatch.setattr(
        "feed.services.fanout_audience",
        lambda a: {"followers": [follower], "friends": [], "recipients": [follower]},
    )
    services.fan_out_post(_payload(author, "public"))
    assert FeedItem.objects.filter(recipient_id=follower, author_id=author).exists()

    from tara_events.envelope import EventEnvelope

    handlers.on_user_unfollowed(
        EventEnvelope(
            event_type="user.unfollowed",
            subject_id=author,
            producer="graph-service",
            payload={"follower": follower, "target": author, "target_type": "user"},
        )
    )
    assert not FeedItem.objects.filter(recipient_id=follower, author_id=author).exists()


# ---- keeping feeds in step with the post -------------------------------------


def _item(recipient: str, author: str, audience: str = "public") -> FeedItem:
    return FeedItem.objects.create(
        recipient_id=recipient,
        post_id=uuid.uuid4(),
        author_id=author,
        reason="friend",
        snapshot={"excerpt": "old", "audience": audience},
        post_created_at=timezone.now(),
    )


def test_deleted_post_leaves_feeds():
    item = _item(_acct(), _acct())
    services.remove_post(str(item.post_id))
    assert not FeedItem.objects.filter(pk=item.pk).exists()


def test_edited_post_updates_the_stored_excerpt():
    item = _item(_acct(), _acct())
    services.update_post_excerpt(str(item.post_id), "new")
    item.refresh_from_db()
    assert item.snapshot["excerpt"] == "new"


def test_unfriending_removes_only_friends_only_posts():
    a, b = _acct(), _acct()
    friends_only = _item(a, b, "friends")
    public = _item(a, b, "public")

    services.remove_friends_only_posts(a, b)

    assert not FeedItem.objects.filter(pk=friends_only.pk).exists()
    assert FeedItem.objects.filter(pk=public.pk).exists()
