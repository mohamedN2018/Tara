"""Feed fan-out + read tests (Graph audience mocked)."""

import uuid

import jwt
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone

from feed import clients, handlers, services
from feed.clients import GraphUnavailable, Relationship
from feed.models import FeedItem, OutboxEvent
from tara_events.envelope import EventEnvelope
from tara_resilience import CircuitBreaker

pytestmark = pytest.mark.django_db

LOW = "00000000-0000-4000-8000-000000000001"
HIGH = "ffffffff-ffff-4fff-bfff-ffffffffffff"


def _acct() -> str:
    return str(uuid.uuid4())


def _payload(
    author_id: str,
    audience: str = "public",
    post_id: str | None = None,
    media_ids: list[str] | None = None,
) -> dict:
    return {
        "post_id": post_id or str(uuid.uuid4()),
        "author_id": author_id,
        "author_type": "user",
        "type": "text",
        "audience": audience,
        "excerpt": "hello world",
        "media_ids": media_ids or [],
        "created_at": timezone.now().isoformat(),
    }


def _audience(monkeypatch, *, followers=(), friends=()):
    """Graph's fan-out answer for any author."""
    monkeypatch.setattr(
        "feed.services.fanout_audience",
        lambda a: {
            "followers": list(followers),
            "friends": list(friends),
            "recipients": sorted(set(followers) | set(friends)),
        },
    )


def _graph_now(monkeypatch, *, friends=(), follows=(), down=False):
    """Graph's current relationships: ``friends`` pairs, ``follows`` (follower, target) pairs."""
    friend_pairs = {frozenset(p) for p in friends}
    follow_pairs = set(follows)

    def _fake(a, b):
        if down:
            raise GraphUnavailable("graph down")
        return Relationship(
            are_friends=frozenset((a, b)) in friend_pairs,
            a_follows_b=(a, b) in follow_pairs,
            b_follows_a=(b, a) in follow_pairs,
        )

    monkeypatch.setattr("feed.services.relationship", _fake)


def _event(event_type: str, payload: dict) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        subject_id=str(uuid.uuid4()),
        producer="graph-service",
        payload=payload,
    )


def _reasons(post_id: str) -> dict[str, str]:
    return {str(i.recipient_id): i.reason for i in FeedItem.objects.filter(post_id=post_id)}


def _has(recipient: str, post_id: str) -> bool:
    return FeedItem.objects.filter(recipient_id=recipient, post_id=post_id).exists()


@pytest.fixture
def no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


# ---- fan-out: who receives a post, and why ------------------------------------


def test_public_fanout_reaches_followers_friends_and_author(monkeypatch):
    author, follower, friend = _acct(), _acct(), _acct()
    _audience(monkeypatch, followers=[follower], friends=[friend])
    payload = _payload(author, "public")
    created = services.fan_out_post(payload)
    assert created == 3  # follower, friend, author
    assert _reasons(payload["post_id"]) == {author: "self", friend: "friend", follower: "follow"}
    summary = OutboxEvent.objects.get(event_type="feed.item.added")  # one row, not one per reader
    assert sorted(summary.payload["payload"]["recipients"]) == sorted([author, follower, friend])

    # Idempotent re-delivery -> no new items.
    assert services.fan_out_post(payload) == 0


def test_followers_audience_reaches_friends_who_do_not_follow(monkeypatch):
    author, follower, friend, stranger = _acct(), _acct(), _acct(), _acct()
    _audience(monkeypatch, followers=[follower], friends=[friend])
    payload = _payload(author, "followers")

    assert services.fan_out_post(payload) == 3
    assert _reasons(payload["post_id"]) == {author: "self", friend: "friend", follower: "follow"}
    assert not _has(stranger, payload["post_id"])


def test_friends_audience_skips_followers(monkeypatch):
    author, follower, friend = _acct(), _acct(), _acct()
    _audience(monkeypatch, followers=[follower], friends=[friend])
    payload = _payload(author, "friends")

    services.fan_out_post(payload)
    assert _reasons(payload["post_id"]) == {author: "self", friend: "friend"}


def test_a_friend_who_also_follows_is_labelled_friend(monkeypatch):
    author, both = _acct(), _acct()
    _audience(monkeypatch, followers=[both], friends=[both])
    payload = _payload(author, "public")

    assert services.fan_out_post(payload) == 2
    assert _reasons(payload["post_id"]) == {author: "self", both: "friend"}


def test_only_me_fanout_skips_graph(monkeypatch):
    author = _acct()

    def _boom(_a):
        raise AssertionError("graph should not be called for only_me")

    monkeypatch.setattr("feed.services.fanout_audience", _boom)
    payload = _payload(author, "only_me")
    assert services.fan_out_post(payload) == 1
    assert FeedItem.objects.filter(recipient_id=author).count() == 1


@pytest.mark.parametrize("audience", ["close_friends", "group", ""])
def test_unknown_audience_reaches_only_the_author(monkeypatch, audience):
    author = _acct()

    def _boom(_a):
        raise AssertionError("graph should not be called for an unknown audience")

    monkeypatch.setattr("feed.services.fanout_audience", _boom)
    payload = _payload(author, audience)
    assert services.fan_out_post(payload) == 1
    assert _reasons(payload["post_id"]) == {author: "self"}


def test_graph_down_makes_fanout_raise_for_a_retry(monkeypatch):
    def _down(_a):
        raise GraphUnavailable("graph down")

    monkeypatch.setattr("feed.services.fanout_audience", _down)
    payload = _payload(_acct(), "followers")
    with pytest.raises(GraphUnavailable):
        services.fan_out_post(payload)
    assert not FeedItem.objects.filter(post_id=payload["post_id"]).exists()


# ---- the fan-out cap -----------------------------------------------------------


def test_cap_always_keeps_the_author(monkeypatch, settings):
    settings.FANOUT_MAX_RECIPIENTS = 3
    author = HIGH  # sorts after every follower, so a naive cut would drop it
    followers = [_acct() for _ in range(10)]
    _audience(monkeypatch, followers=followers)
    payload = _payload(author, "public")

    assert services.fan_out_post(payload) == 3
    reasons = _reasons(payload["post_id"])
    assert reasons[author] == "self"
    assert sorted(reasons.values()) == ["follow", "follow", "self"]
    summary = OutboxEvent.objects.get(event_type="feed.item.added")
    assert sorted(summary.payload["payload"]["recipients"]) == sorted(reasons)

    # Re-delivery neither adds the dropped followers nor removes anything.
    assert services.fan_out_post(payload) == 0
    assert len(_reasons(payload["post_id"])) == 3


def test_cap_prefers_friends_over_followers(monkeypatch, settings):
    settings.FANOUT_MAX_RECIPIENTS = 3
    author = _acct()
    friends = [_acct(), _acct()]
    _audience(monkeypatch, followers=[_acct() for _ in range(10)], friends=friends)
    payload = _payload(author, "followers")

    services.fan_out_post(payload)
    assert _reasons(payload["post_id"]) == {
        author: "self",
        friends[0]: "friend",
        friends[1]: "friend",
    }


@pytest.mark.parametrize("cap", [1, 0])
def test_tiny_cap_still_keeps_the_author(monkeypatch, settings, cap):
    settings.FANOUT_MAX_RECIPIENTS = cap
    author = HIGH
    _audience(monkeypatch, followers=[_acct() for _ in range(5)], friends=[LOW])
    payload = _payload(author, "public")

    assert services.fan_out_post(payload) == 1
    assert _reasons(payload["post_id"]) == {author: "self"}


# ---- what GET /feed/ returns ---------------------------------------------------


def test_home_feed_endpoint(client_for, monkeypatch):
    author, viewer = _acct(), _acct()
    _audience(monkeypatch, followers=[viewer])
    services.fan_out_post(_payload(author, "public"))

    resp = client_for(viewer).get(reverse("feed:home-feed"))
    assert resp.status_code == 200
    body = resp.json()
    assert "page" in body
    assert len(body["data"]) == 1
    assert body["data"][0]["snapshot"]["excerpt"] == "hello world"
    assert body["data"][0]["reason"] == "follow"


def test_home_feed_blends_sponsored_slot(client_for, monkeypatch):
    author, viewer = _acct(), _acct()
    _audience(monkeypatch, followers=[viewer])
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


def test_home_feed_requires_authentication():
    from rest_framework.test import APIClient

    assert APIClient().get(reverse("feed:home-feed")).status_code == 401


def test_feed_returns_ids_only_for_non_public_items(client_for, monkeypatch, no_ads):
    author, friend = _acct(), _acct()
    media = [str(uuid.uuid4())]
    _audience(monkeypatch, followers=[friend], friends=[friend])
    for audience in ("public", "followers", "friends"):
        services.fan_out_post(_payload(author, audience, media_ids=media))

    items = client_for(friend).get(reverse("feed:home-feed")).json()["data"]
    by_audience = {i["snapshot"]["audience"]: i["snapshot"] for i in items}
    assert by_audience["public"]["excerpt"] == "hello world"
    assert by_audience["public"]["media_ids"] == media
    for audience in ("followers", "friends"):
        snap = by_audience[audience]
        assert "excerpt" not in snap
        assert "media_ids" not in snap
        assert set(snap) <= set(services._ID_KEYS)
        assert snap["author_id"] == author


def test_non_public_content_is_not_even_stored_for_other_readers(monkeypatch):
    author, friend = _acct(), _acct()
    _audience(monkeypatch, friends=[friend])
    payload = _payload(author, "friends", media_ids=[str(uuid.uuid4())])
    services.fan_out_post(payload)

    stored = FeedItem.objects.get(recipient_id=friend, post_id=payload["post_id"]).snapshot
    assert "excerpt" not in stored
    assert "media_ids" not in stored
    own = FeedItem.objects.get(recipient_id=author, post_id=payload["post_id"]).snapshot
    assert own["excerpt"] == "hello world"


def test_author_sees_own_non_public_snapshot(client_for, monkeypatch, no_ads):
    author = _acct()
    _audience(monkeypatch, friends=[_acct()])
    services.fan_out_post(_payload(author, "friends", media_ids=["m1"]))

    [item] = client_for(author).get(reverse("feed:home-feed")).json()["data"]
    assert item["reason"] == "self"
    assert item["snapshot"]["excerpt"] == "hello world"
    assert item["snapshot"]["media_ids"] == ["m1"]


@pytest.mark.parametrize(
    "stored",
    [
        {"audience": "followers", "excerpt": "secret", "media_ids": ["m1"], "body": "x"},
        {"audience": "friends", "excerpt": "secret", "media_ids": ["m1"]},
        {"excerpt": "secret", "media_ids": ["m1"]},  # no audience: fail closed
    ],
)
def test_feed_strips_content_from_stored_legacy_snapshots(client_for, no_ads, stored):
    """Rows written before the fix still hold content; the read path never returns it."""
    viewer, author = _acct(), _acct()
    FeedItem.objects.create(
        recipient_id=viewer,
        post_id=uuid.uuid4(),
        author_id=author,
        reason="follow",
        snapshot={**stored, "author_id": author},
        post_created_at=timezone.now(),
    )
    [item] = client_for(viewer).get(reverse("feed:home-feed")).json()["data"]
    assert "excerpt" not in item["snapshot"]
    assert "media_ids" not in item["snapshot"]
    assert "body" not in item["snapshot"]
    assert item["snapshot"]["author_id"] == author


def test_feed_never_returns_another_readers_items(client_for, monkeypatch, no_ads):
    author, follower, stranger = _acct(), _acct(), _acct()
    _audience(monkeypatch, followers=[follower])
    services.fan_out_post(_payload(author, "public"))

    assert client_for(stranger).get(reverse("feed:home-feed")).json()["data"] == []


# ---- unfollow ------------------------------------------------------------------


def test_unfollow_removes_author_items(monkeypatch):
    author, follower = _acct(), _acct()
    _audience(monkeypatch, followers=[follower])
    services.fan_out_post(_payload(author, "public"))
    assert FeedItem.objects.filter(recipient_id=follower, author_id=author).exists()

    handlers.on_user_unfollowed(
        _event("user.unfollowed", {"follower": follower, "target": author, "target_type": "user"})
    )
    assert not FeedItem.objects.filter(recipient_id=follower, author_id=author).exists()


def test_unfollow_keeps_friend_items(monkeypatch):
    author, friend = _acct(), _acct()
    _audience(monkeypatch, followers=[friend], friends=[friend])
    friend_post = _payload(author, "followers")
    services.fan_out_post(friend_post)
    # An older item that reached them through the follow alone.
    _audience(monkeypatch, followers=[friend])
    follow_post = _payload(author, "public")
    services.fan_out_post(follow_post)

    handlers.on_user_unfollowed(
        _event("user.unfollowed", {"follower": friend, "target": author, "target_type": "user"})
    )
    assert _has(friend, friend_post["post_id"])
    assert not _has(friend, follow_post["post_id"])
    assert _has(author, follow_post["post_id"])  # the author's own items are untouched


def test_unfollowing_a_page_changes_nothing(monkeypatch):
    author, follower = _acct(), _acct()
    _audience(monkeypatch, followers=[follower])
    payload = _payload(author, "public")
    services.fan_out_post(payload)

    handlers.on_user_unfollowed(
        _event("user.unfollowed", {"follower": follower, "target": author, "target_type": "page"})
    )
    assert _has(follower, payload["post_id"])


# ---- unfriend ------------------------------------------------------------------


def _three_posts(monkeypatch, author: str, friend: str) -> dict[str, str]:
    """One post per audience from ``author``, fanned out while ``friend`` was a friend."""
    _audience(monkeypatch, friends=[friend])
    posts = {}
    for audience in ("public", "followers", "friends"):
        payload = _payload(author, audience)
        services.fan_out_post(payload)
        posts[audience] = payload["post_id"]
    return posts


def _unfriend(a: str, b: str) -> None:
    handlers.on_friendship_removed(_event("friendship.removed", {"a": a, "b": b}))


def _feed_post_ids(client) -> set[str]:
    return {i["post_id"] for i in client.get(reverse("feed:home-feed")).json()["data"]}


def test_unfriend_drops_followers_items_for_an_ex_friend_who_does_not_follow(
    client_for, monkeypatch, no_ads
):
    author, friend = _acct(), _acct()
    posts = _three_posts(monkeypatch, author, friend)
    assert _feed_post_ids(client_for(friend)) == set(posts.values())  # friend, not a follower

    _graph_now(monkeypatch)  # no friendship, no follows
    _unfriend(author, friend)

    # No connection left: nothing of the author's stays, public included (as after
    # an unfollow). Previously the public item stayed, still labelled `friend`.
    assert _feed_post_ids(client_for(friend)) == set()
    # The author's own items stay.
    assert all(_has(author, p) for p in posts.values())


def test_unfriend_keeps_followers_items_for_an_ex_friend_who_follows(monkeypatch):
    author, friend = _acct(), _acct()
    posts = _three_posts(monkeypatch, author, friend)

    _graph_now(monkeypatch, follows=[(friend, author)])
    _unfriend(author, friend)

    assert not _has(friend, posts["friends"])
    kept = FeedItem.objects.filter(recipient_id=friend, author_id=author)
    assert {str(i.post_id) for i in kept} == {posts["public"], posts["followers"]}
    assert {i.reason for i in kept} == {"follow"}  # now there through the follow

    # So a later unfollow cleans them up.
    handlers.on_user_unfollowed(
        _event("user.unfollowed", {"follower": friend, "target": author, "target_type": "user"})
    )
    assert not FeedItem.objects.filter(recipient_id=friend, author_id=author).exists()


def test_unfriend_cleans_both_sides(monkeypatch):
    a, b = LOW, HIGH
    a_posts = _three_posts(monkeypatch, a, b)
    b_posts = _three_posts(monkeypatch, b, a)

    _graph_now(monkeypatch, follows=[(a, b)])  # a still follows b; b does not follow a
    _unfriend(a, b)

    # b does not follow a: none of a's posts stay in b's feed.
    assert not FeedItem.objects.filter(recipient_id=b, author_id=a).exists()
    assert all(_has(a, p) for p in a_posts.values())
    # a keeps b's followers post because a follows b.
    assert {str(i.post_id) for i in FeedItem.objects.filter(recipient_id=a, author_id=b)} == {
        b_posts["public"],
        b_posts["followers"],
    }


def test_unfriend_fails_closed_when_graph_is_down(monkeypatch):
    author, friend = _acct(), _acct()
    posts = _three_posts(monkeypatch, author, friend)

    _graph_now(monkeypatch, follows=[(friend, author)], down=True)
    _unfriend(author, friend)  # does not raise

    # Unknown follow state -> treated as not following.
    assert not FeedItem.objects.filter(recipient_id=friend).exists()
    assert all(_has(author, p) for p in posts.values())


def test_a_stale_unfriend_after_refriending_changes_nothing(monkeypatch):
    author, friend = _acct(), _acct()
    posts = _three_posts(monkeypatch, author, friend)

    _graph_now(monkeypatch, friends=[(author, friend)])  # friends again by now
    _unfriend(author, friend)

    assert all(_has(friend, p) for p in posts.values())


def test_unfriending_keeps_public_posts_only_for_a_side_that_follows(monkeypatch):
    a, b = _acct(), _acct()
    friends_only = _item(a, b, "friends")
    public = _item(a, b, "public")
    other_way = _item(b, a, "public")

    _graph_now(monkeypatch, follows=[(a, b)])  # a follows b, b does not follow a
    services.apply_unfriend(a, b)

    assert not FeedItem.objects.filter(pk=friends_only.pk).exists()
    public.refresh_from_db()
    assert public.reason == "follow"
    assert not FeedItem.objects.filter(pk=other_way.pk).exists()


def test_an_ex_friend_who_follows_loses_the_post_when_it_becomes_friends_only(
    client_for, monkeypatch, no_ads
):
    author, friend = _acct(), _acct()
    posts = _three_posts(monkeypatch, author, friend)
    _graph_now(monkeypatch, follows=[(friend, author)])
    _unfriend(author, friend)

    _edit(posts["public"], "friends")
    _edit(posts["followers"], "followers", excerpt="still followers")

    # Relabelled `follow` at the unfriend, so the friends-only edit drops it.
    assert _feed_post_ids(client_for(friend)) == {posts["followers"]}


# ---- a new friendship ----------------------------------------------------------


def test_new_friendship_relabels_follow_items_both_ways(monkeypatch):
    a, b = _acct(), _acct()
    _audience(monkeypatch, followers=[b])
    a_post = _payload(a, "public")
    services.fan_out_post(a_post)
    _audience(monkeypatch, followers=[a])
    b_post = _payload(b, "public")
    services.fan_out_post(b_post)

    _graph_now(monkeypatch, friends=[(a, b)])
    handlers.on_friendship_accepted(_event("friendship.accepted", {"a": a, "b": b}))

    assert _reasons(a_post["post_id"]) == {a: "self", b: "friend"}
    assert _reasons(b_post["post_id"]) == {b: "self", a: "friend"}


def test_a_stale_friendship_accepted_changes_nothing(monkeypatch):
    a, b = _acct(), _acct()
    _audience(monkeypatch, followers=[b])
    post = _payload(a, "public")
    services.fan_out_post(post)

    _graph_now(monkeypatch)  # unfriended since
    handlers.on_friendship_accepted(_event("friendship.accepted", {"a": a, "b": b}))

    assert _reasons(post["post_id"]) == {a: "self", b: "follow"}


def test_friendship_accepted_retries_when_graph_is_down(monkeypatch):
    a, b = _acct(), _acct()
    _graph_now(monkeypatch, down=True)
    with pytest.raises(GraphUnavailable):
        handlers.on_friendship_accepted(_event("friendship.accepted", {"a": a, "b": b}))


# ---- block ---------------------------------------------------------------------


def test_block_removes_everything_between_the_two(monkeypatch):
    author, friend = _acct(), _acct()
    posts = _three_posts(monkeypatch, author, friend)

    handlers.on_user_blocked(_event("user.blocked", {"blocker_id": author, "blocked_id": friend}))
    assert not FeedItem.objects.filter(recipient_id=friend).exists()
    assert all(_has(author, p) for p in posts.values())


# ---- keeping feeds in step with the post -------------------------------------


def _item(
    recipient: str, author: str, audience: str = "public", reason: str = "friend"
) -> FeedItem:
    return FeedItem.objects.create(
        recipient_id=recipient,
        post_id=uuid.uuid4(),
        author_id=author,
        reason=reason,
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


def _edit(post_id: str, audience: str | None, excerpt: str = "edited", **extra) -> None:
    payload = {"post_id": post_id, "excerpt": excerpt, **extra}
    if audience is not None:
        payload["audience"] = audience
    handlers.on_post_updated(_event("post.updated", payload))


def _fan_out_to_both(monkeypatch, audience: str = "public", media_ids=("m1",)):
    """A post from ``author`` reaching a pure ``follower`` and a ``friend``."""
    author, follower, friend = _acct(), _acct(), _acct()
    _audience(monkeypatch, followers=[follower], friends=[friend])
    payload = _payload(author, audience, media_ids=list(media_ids))
    services.fan_out_post(payload)
    return author, follower, friend, payload["post_id"]


def _feed(client) -> list[dict]:
    return client.get(reverse("feed:home-feed")).json()["data"]


def test_edit_that_narrows_the_audience_drops_stored_content(monkeypatch):
    # Updated: this used to keep the pure follower's row for a friends-only post.
    author, follower, friend, post_id = _fan_out_to_both(monkeypatch)

    _edit(post_id, "friends")

    assert not _has(follower, post_id)
    theirs = FeedItem.objects.get(recipient_id=friend, post_id=post_id).snapshot
    assert theirs["audience"] == "friends"
    assert "excerpt" not in theirs
    assert "media_ids" not in theirs
    own = FeedItem.objects.get(recipient_id=author, post_id=post_id).snapshot
    assert own["excerpt"] == "edited"
    assert own["media_ids"] == ["m1"]


def test_feed_after_public_to_only_me_shows_the_post_to_nobody_else(
    client_for, monkeypatch, no_ads
):
    author, follower, friend, post_id = _fan_out_to_both(monkeypatch)

    _edit(post_id, "only_me")

    assert _feed(client_for(follower)) == []
    assert _feed(client_for(friend)) == []
    [own] = _feed(client_for(author))
    assert own["post_id"] == post_id
    assert own["reason"] == "self"
    assert own["snapshot"]["audience"] == "only_me"
    assert own["snapshot"]["excerpt"] == "edited"
    assert own["snapshot"]["media_ids"] == ["m1"]


def test_feed_after_public_to_friends_drops_a_pure_follower(client_for, monkeypatch, no_ads):
    author, follower, friend, post_id = _fan_out_to_both(monkeypatch)

    _edit(post_id, "friends")

    assert _feed(client_for(follower)) == []
    [item] = _feed(client_for(friend))
    assert item["post_id"] == post_id
    assert item["reason"] == "friend"
    assert set(item["snapshot"]) <= set(services._ID_KEYS)  # ids only: hydrate via batch
    assert item["snapshot"]["audience"] == "friends"


def test_feed_after_public_to_followers_keeps_friends_and_followers_as_ids(
    client_for, monkeypatch, no_ads
):
    author, follower, friend, post_id = _fan_out_to_both(monkeypatch)

    _edit(post_id, "followers")

    for viewer, reason in ((follower, "follow"), (friend, "friend")):
        [item] = _feed(client_for(viewer))
        assert (item["post_id"], item["reason"]) == (post_id, reason)
        assert "excerpt" not in item["snapshot"]
        assert "media_ids" not in item["snapshot"]


def test_followers_to_friends_drops_follow_rows_only(monkeypatch):
    author, follower, friend, post_id = _fan_out_to_both(monkeypatch, "followers")

    _edit(post_id, "friends")

    assert _reasons(post_id) == {author: "self", friend: "friend"}


def test_a_friend_who_also_follows_keeps_a_friends_only_post(monkeypatch):
    author, both = _acct(), _acct()
    _audience(monkeypatch, followers=[both], friends=[both])
    payload = _payload(author, "public")
    services.fan_out_post(payload)

    _edit(payload["post_id"], "friends")

    assert _reasons(payload["post_id"]) == {author: "self", both: "friend"}


@pytest.mark.parametrize("audience", ["close_friends", "group", ""])
def test_edit_to_an_unknown_audience_keeps_the_author_alone(monkeypatch, audience):
    author, _follower, _friend, post_id = _fan_out_to_both(monkeypatch)

    _edit(post_id, audience)

    assert _reasons(post_id) == {author: "self"}


def test_edit_without_an_audience_drops_nobody(monkeypatch):
    author, follower, friend, post_id = _fan_out_to_both(monkeypatch, "followers")

    _edit(post_id, None, excerpt="typo fixed")

    assert _reasons(post_id) == {author: "self", friend: "friend", follower: "follow"}
    assert FeedItem.objects.get(recipient_id=author, post_id=post_id).snapshot["excerpt"] == (
        "typo fixed"
    )


def test_narrowing_touches_no_other_post(monkeypatch):
    author, follower, friend, post_id = _fan_out_to_both(monkeypatch)
    other = _payload(author, "public")
    services.fan_out_post(other)

    _edit(post_id, "only_me")

    assert _reasons(other["post_id"]) == {author: "self", friend: "friend", follower: "follow"}


def test_a_redelivered_narrowing_edit_is_harmless(monkeypatch):
    author, follower, friend, post_id = _fan_out_to_both(monkeypatch)

    _edit(post_id, "friends")
    _edit(post_id, "friends")

    assert _reasons(post_id) == {author: "self", friend: "friend"}


def test_widening_to_public_restores_excerpt_and_media(client_for, monkeypatch, no_ads):
    author, follower, friend, post_id = _fan_out_to_both(monkeypatch, "followers")
    stored = FeedItem.objects.get(recipient_id=follower, post_id=post_id).snapshot
    assert "media_ids" not in stored

    _edit(post_id, "public", excerpt="now public")

    for viewer in (follower, friend):
        [item] = _feed(client_for(viewer))
        assert item["snapshot"]["excerpt"] == "now public"
        assert item["snapshot"]["media_ids"] == ["m1"]  # from the author's own item


def test_widening_prefers_media_ids_from_the_event(monkeypatch):
    author, follower, _friend, post_id = _fan_out_to_both(monkeypatch, "followers")

    _edit(post_id, "public", media_ids=["m2"])

    assert FeedItem.objects.get(recipient_id=follower, post_id=post_id).snapshot["media_ids"] == [
        "m2"
    ]


def test_widening_without_any_media_source_leaves_media_absent():
    """No author item and no media in the event: the client hydrates the media."""
    item = _item(_acct(), _acct(), "followers", reason="follow")

    services.update_post_excerpt(str(item.post_id), "now public", "public")

    item.refresh_from_db()
    assert item.snapshot["excerpt"] == "now public"
    assert "media_ids" not in item.snapshot


def test_edit_of_a_non_public_post_stores_no_excerpt_for_readers():
    item = _item(_acct(), _acct(), "followers")
    services.update_post_excerpt(str(item.post_id), "new")
    item.refresh_from_db()
    assert "excerpt" not in item.snapshot


# ---- relabel_feed_reasons (one-off data fix) ----------------------------------


def _legacy(recipient: str, author: str) -> FeedItem:
    """Before 1.1 every non-self item was stored as `follow`."""
    return _item(recipient, author, reason="follow")


def _friends_of(monkeypatch, friends: dict[str, list[str]], *, down_for: str | None = None):
    calls = []

    def _fake(account_id):
        calls.append(account_id)
        if account_id == down_for:
            raise GraphUnavailable("graph down")
        return {"followers": [], "friends": friends.get(account_id, [])}

    monkeypatch.setattr("feed.clients.fanout_audience", _fake)
    return calls


def test_relabel_command_labels_items_between_friends(monkeypatch, capsys):
    r1, r2, friend, stranger = LOW, HIGH, _acct(), _acct()
    from_friend = _legacy(r1, friend)
    from_stranger = _legacy(r1, stranger)
    other = _legacy(r2, friend)
    own = _item(r1, r1, reason="self")
    _friends_of(monkeypatch, {r1: [friend], r2: []})

    call_command("relabel_feed_reasons", "--batch-size", "1")

    def reason(item):
        item.refresh_from_db()
        return item.reason

    assert reason(from_friend) == "friend"
    assert reason(from_stranger) == "follow"
    assert reason(other) == "follow"
    assert reason(own) == "self"
    assert "relabelled 1 items across 2 recipients" in capsys.readouterr().out

    # Running it again changes nothing.
    call_command("relabel_feed_reasons")
    assert "relabelled 0 items" in capsys.readouterr().out


def test_relabel_command_dry_run_changes_nothing(monkeypatch, capsys):
    recipient, friend = _acct(), _acct()
    item = _legacy(recipient, friend)
    _friends_of(monkeypatch, {recipient: [friend]})

    call_command("relabel_feed_reasons", "--dry-run")

    item.refresh_from_db()
    assert item.reason == "follow"
    assert "would relabel 1 items across 1 recipients" in capsys.readouterr().out


def test_relabel_command_stops_on_graph_failure_and_resumes(monkeypatch):
    r1, r2, friend = LOW, HIGH, _acct()
    first, second = _legacy(r1, friend), _legacy(r2, friend)
    _friends_of(monkeypatch, {r1: [friend], r2: [friend]}, down_for=r2)

    with pytest.raises(CommandError, match=f"--after {r1}"):
        call_command("relabel_feed_reasons")
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.reason, second.reason) == ("friend", "follow")  # r1 already committed

    calls = _friends_of(monkeypatch, {r1: [friend], r2: [friend]})
    call_command("relabel_feed_reasons", "--after", r1)
    second.refresh_from_db()
    assert second.reason == "friend"
    assert calls == [r2]  # r1 is not looked up again


# ---- graph client --------------------------------------------------------------


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


def test_relationship_client_sends_an_internal_token_and_parses(monkeypatch, settings):
    seen = {}

    def _get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers, timeout=timeout)
        return _Resp({"are_friends": False, "a_follows_b": True, "b_follows_a": False})

    monkeypatch.setattr(clients, "_relationship_breaker", CircuitBreaker(name="t"))
    monkeypatch.setattr(clients.requests, "get", _get)

    rel = clients.relationship("a-id", "b-id")

    assert rel == Relationship(are_friends=False, a_follows_b=True)
    assert seen["url"].endswith("/internal/v1/relationship/")
    assert seen["params"] == {"a": "a-id", "b": "b-id"}
    assert seen["timeout"] == settings.GRAPH_CALL_TIMEOUT
    token = seen["headers"]["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(
        token, settings.TARA_INTERNAL_JWT_SECRET, algorithms=["HS256"], audience="graph-internal"
    )
    assert claims["iss"] == "feed"
    assert claims["exp"] - claims["iat"] <= 30


def test_relationship_client_raises_graph_unavailable(monkeypatch):
    def _boom(*args, **kwargs):
        raise ConnectionError("refused")

    monkeypatch.setattr(clients, "_relationship_breaker", CircuitBreaker(name="t"))
    monkeypatch.setattr(clients.requests, "get", _boom)

    with pytest.raises(GraphUnavailable):
        clients.relationship("a-id", "b-id")
