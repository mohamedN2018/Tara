"""2A / roadmap 1.7: hide, snooze, feed modes and ranking v1."""

import uuid
from datetime import timedelta

import pytest
from django.core.cache import caches
from django.urls import reverse
from django.utils import timezone

from feed import handlers, ranking, services
from feed.models import (
    Affinity,
    AuthorRef,
    AuthorSnooze,
    FeedItem,
    FollowEdge,
    PostHide,
    PostStats,
    ProcessedEvent,
    RelationshipFlag,
)
from tara_events.consumer import idempotent
from tara_events.dispatch import handlers_for
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

MODES = ("recent", "for_you", "favorites", "following")


def _acct() -> str:
    return str(uuid.uuid4())


def _item(viewer, author, *, minutes_ago=0, reason="follow", audience="public", post_id=None):
    post_id = post_id or str(uuid.uuid4())
    return FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason=reason,
        snapshot={
            "post_id": post_id,
            "author_id": author,
            "audience": audience,
            "excerpt": "hi",
            "media_ids": [],
        },
        post_created_at=timezone.now() - timedelta(minutes=minutes_ago),
    )


def _event(event_type: str, payload: dict, *, subject=None, at=None) -> EventEnvelope:
    kwargs = {"occurred_at": at.isoformat()} if at is not None else {}
    return EventEnvelope(
        event_type=event_type,
        subject_id=subject or str(uuid.uuid4()),
        producer="test",
        payload=payload,
        **kwargs,
    )


def _deliver(event: EventEnvelope) -> None:
    """As the worker does: each handler runs once per event id."""
    for fn in handlers_for(event.event_type):
        with idempotent(ProcessedEvent, event.event_id, f"feed:{fn.__name__}") as fresh:
            if fresh:
                fn(event)


def _pages(client, mode, limit=5, max_pages=50):
    """Every page of a mode: ([post ids per page], last body)."""
    pages, cursor, body = [], None, None
    for _ in range(max_pages):
        params = {"mode": mode, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        resp = client.get(reverse("feed:home-feed"), params)
        assert resp.status_code == 200, resp.content
        body = resp.json()
        pages.append([i["post_id"] for i in body["data"]])
        cursor = body["page"]["next_cursor"]
        if not cursor:
            break
    return pages, body


def _all(client, mode, limit=5):
    return [p for page in _pages(client, mode, limit)[0] for p in page]


@pytest.fixture(autouse=True)
def no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


@pytest.fixture
def world():
    """A viewer with 12 posts from one followed author (also a favorite)."""
    viewer, author = _acct(), _acct()
    items = [_item(viewer, author, minutes_ago=i) for i in range(12)]
    RelationshipFlag.objects.create(
        actor_id=viewer, target_id=author, kind="favorite", occurred_at=timezone.now()
    )
    return viewer, author, items


# ---- hide ---------------------------------------------------------------------


def test_hidden_post_never_appears_on_any_page_of_any_mode(client_for, world):
    viewer, _, items = world
    client = client_for(viewer)
    hidden = str(items[7].post_id)  # on page 2 of 5
    resp = client.post(reverse("feed:hide"), {"post_id": hidden, "reason": "not_interested"})
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["post_id"] == hidden and data["reason"] == "not_interested" and data["hidden_at"]

    for mode in MODES:
        seen = _all(client, mode)
        assert hidden not in seen, mode
        assert len(seen) == 11, mode


def test_undo_brings_the_post_back(client_for, world):
    viewer, _, items = world
    client = client_for(viewer)
    post = str(items[3].post_id)
    client.post(reverse("feed:hide"), {"post_id": post, "reason": "other"})
    assert post not in _all(client, "recent")

    assert client.delete(reverse("feed:unhide", args=[post])).status_code == 204
    for mode in MODES:
        assert post in _all(client, mode), mode
    # Undo again: still 204.
    assert client.delete(reverse("feed:unhide", args=[post])).status_code == 204


def test_hide_is_idempotent_and_a_new_reason_replaces_the_old(client_for, world):
    viewer, _, items = world
    client = client_for(viewer)
    post = str(items[0].post_id)
    first = client.post(reverse("feed:hide"), {"post_id": post, "reason": "spam"}).json()["data"]
    again = client.post(reverse("feed:hide"), {"post_id": post, "reason": "spam"})
    assert again.status_code == 201
    assert again.json()["data"]["hidden_at"] == first["hidden_at"]
    assert PostHide.objects.filter(account_id=viewer, post_id=post).count() == 1
    assert PostStats.objects.get(post_id=post).flags == 1  # counted once

    changed = client.post(reverse("feed:hide"), {"post_id": post, "reason": "annoying"})
    assert changed.json()["data"]["reason"] == "annoying"
    assert PostStats.objects.get(post_id=post).flags == 0


def test_hide_validates_and_is_404_for_a_post_outside_my_feed(client_for, world):
    viewer, author, _ = world
    client = client_for(viewer)
    other = _item(_acct(), author)  # someone else's feed row
    resp = client.post(reverse("feed:hide"), {"post_id": str(other.post_id), "reason": "spam"})
    assert resp.status_code == 404
    resp = client.post(reverse("feed:hide"), {"post_id": str(uuid.uuid4()), "reason": "spam"})
    assert resp.status_code == 404
    resp = client.post(reverse("feed:hide"), {"post_id": str(other.post_id), "reason": "boring"})
    assert resp.status_code == 400
    assert not PostHide.objects.exists()


def test_feed_endpoints_require_authentication():
    from rest_framework.test import APIClient

    anon = APIClient()
    pid = str(uuid.uuid4())
    assert anon.post(reverse("feed:hide"), {"post_id": pid, "reason": "spam"}).status_code == 401
    assert anon.delete(reverse("feed:unhide", args=[pid])).status_code == 401
    assert anon.post(reverse("feed:snooze"), {"author_id": pid}).status_code == 401
    assert anon.get(reverse("feed:snoozes")).status_code == 401


def test_one_viewers_hide_leaves_other_viewers_alone(client_for):
    a, b, author = _acct(), _acct(), _acct()
    post = str(uuid.uuid4())
    _item(a, author, post_id=post)
    _item(b, author, post_id=post)
    client_for(a).post(reverse("feed:hide"), {"post_id": post, "reason": "not_interested"})
    assert _all(client_for(a), "recent") == []
    assert _all(client_for(b), "recent") == [post]


def test_spam_and_sexual_hides_are_kept_as_moderation_signals(
    client_for, django_capture_on_commit_callbacks
):
    author = _acct()
    post = str(uuid.uuid4())
    viewers = [_acct() for _ in range(3)]
    for v in viewers:
        _item(v, author, post_id=post)
    # The feed rows' score is refreshed after the commit (feed.tasks).
    with django_capture_on_commit_callbacks(execute=True):
        for v, reason in zip(viewers, ["spam", "sexual", "not_interested"], strict=True):
            client_for(v).post(reverse("feed:hide"), {"post_id": post, "reason": reason})

    assert PostStats.objects.get(post_id=post).flags == 2
    assert set(
        PostHide.objects.filter(post_id=post, reason__in=["spam", "sexual"]).values_list(
            "reason", flat=True
        )
    ) == {"spam", "sexual"}
    # The flags weigh the post down for everyone (its stored engagement score).
    assert all(i.score < 0 for i in FeedItem.objects.filter(post_id=post))

    client_for(viewers[0]).delete(reverse("feed:unhide", args=[post]))
    assert PostStats.objects.get(post_id=post).flags == 1


@pytest.mark.parametrize("reason", ["dislike_creator", "annoying"])
def test_dislike_and_annoying_push_the_author_down_in_for_you(client_for, reason):
    viewer, liked, disliked = _acct(), _acct(), _acct()
    # The disliked author's posts are the newest.
    for i in range(3):
        _item(viewer, disliked, minutes_ago=i)
        _item(viewer, liked, minutes_ago=10 + i)
    hidden = _item(viewer, disliked, minutes_ago=5)
    before = _all(client_for(viewer), "for_you", limit=20)
    authors = {str(i.post_id): str(i.author_id) for i in FeedItem.objects.all()}
    assert authors[before[0]] == disliked

    client_for(viewer).post(
        reverse("feed:hide"), {"post_id": str(hidden.post_id), "reason": reason}
    )
    after = _all(client_for(viewer), "for_you", limit=20)
    assert [authors[p] for p in after[:3]] == [liked] * 3
    # Latest order is not ranked: it stays chronological.
    recent = _all(client_for(viewer), "recent", limit=20)
    assert authors[recent[0]] == disliked


def test_not_interested_does_not_downweight_the_author(client_for):
    viewer, author = _acct(), _acct()
    hidden = _item(viewer, author, minutes_ago=1)
    _item(viewer, author, minutes_ago=2)
    client_for(viewer).post(
        reverse("feed:hide"), {"post_id": str(hidden.post_id), "reason": "not_interested"}
    )
    assert ranking.author_penalties(viewer, [author]) == {}


# ---- snooze -------------------------------------------------------------------


def test_snooze_hides_the_author_for_30_days(client_for, world):
    viewer, author, _ = world
    other = _acct()
    kept = _item(viewer, other, reason="friend")
    client = client_for(viewer)
    resp = client.post(reverse("feed:snooze"), {"author_id": author})
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["author_id"] == author
    until = AuthorSnooze.objects.get(account_id=viewer, author_id=author).until
    assert timedelta(days=29, hours=23) < until - timezone.now() <= timedelta(days=30)

    for mode in ("recent", "for_you"):
        assert _all(client, mode) == [str(kept.post_id)], mode

    # Thirty days later the snooze is over.
    AuthorSnooze.objects.filter(account_id=viewer).update(
        until=timezone.now() - timedelta(seconds=1)
    )
    assert len(_all(client, "recent")) == 13
    assert client.get(reverse("feed:snoozes")).json()["data"] == []


def test_snooze_list_unsnooze_and_self(client_for, world):
    viewer, author, _ = world
    client = client_for(viewer)
    client.post(reverse("feed:snooze"), {"author_id": author})
    again = client.post(reverse("feed:snooze"), {"author_id": author})
    assert again.status_code == 201
    listed = client.get(reverse("feed:snoozes")).json()
    assert [s["author_id"] for s in listed["data"]] == [author]
    assert "page" in listed

    assert client.delete(reverse("feed:unsnooze", args=[author])).status_code == 204
    assert len(_all(client, "recent")) == 12
    assert client.delete(reverse("feed:unsnooze", args=[author])).status_code == 204

    resp = client.post(reverse("feed:snooze"), {"author_id": viewer})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "cannot_snooze_self"
    assert client.post(reverse("feed:snooze"), {"author_id": "nope"}).status_code == 400


def test_snoozes_are_per_viewer(client_for):
    a, b, author = _acct(), _acct(), _acct()
    _item(a, author)
    _item(b, author)
    client_for(a).post(reverse("feed:snooze"), {"author_id": author})
    assert client_for(b).get(reverse("feed:snoozes")).json()["data"] == []
    assert len(_all(client_for(b), "recent")) == 1


# ---- modes --------------------------------------------------------------------


def test_recent_is_the_old_chronological_order(client_for):
    viewer = _acct()
    authors = [_acct() for _ in range(4)]
    for i in range(23):
        _item(viewer, authors[i % 4], minutes_ago=(i * 7) % 23, reason=["follow", "friend"][i % 2])
    old_order = [
        str(p)
        for p in FeedItem.objects.filter(recipient_id=viewer)
        .order_by("-post_created_at")
        .values_list("post_id", flat=True)
    ]
    assert _all(client_for(viewer), "recent", limit=5) == old_order
    # No mode at all is the same as recent, and says so.
    resp = client_for(viewer).get(reverse("feed:home-feed"), {"limit": 50})
    assert [i["post_id"] for i in resp.json()["data"]] == old_order
    assert resp.json()["mode"] == "recent"


def test_unknown_mode_is_400(client_for):
    resp = client_for(_acct()).get(reverse("feed:home-feed"), {"mode": "best"})
    assert resp.status_code == 400


def test_item_shape_is_unchanged_in_every_mode(client_for, world):
    viewer, _, _ = world
    for mode in MODES:
        body = client_for(viewer).get(reverse("feed:home-feed"), {"mode": mode}).json()
        assert body["mode"] == mode
        assert set(body["data"][0]) == {
            "id",
            "post_id",
            "author_id",
            "reason",
            "score",
            "snapshot",
            "post_created_at",
            # Tara Intelligence WP 2.3 (additive): the serve token that attributes
            # this item's telemetry (intel/ranking/serve_tokens.py).
            "st",
        }
        assert {"next_cursor", "has_more"} <= set(body["page"])


def test_favorites_mode_shows_only_favorited_authors(client_for):
    viewer, fav, other = _acct(), _acct(), _acct()
    f = _item(viewer, fav)
    _item(viewer, other)
    _deliver(
        _event(
            "relationship.favorited",
            {"actor_id": viewer, "target_id": fav, "occurred_at": timezone.now().isoformat()},
        )
    )
    assert _all(client_for(viewer), "favorites") == [str(f.post_id)]

    _deliver(
        _event(
            "relationship.unfavorited",
            {"actor_id": viewer, "target_id": fav, "occurred_at": timezone.now().isoformat()},
        )
    )
    assert _all(client_for(viewer), "favorites") == []


def test_following_mode_shows_only_followed_accounts_and_pages(client_for):
    viewer, followed, friend_followed, friend_only, page = (_acct() for _ in range(5))
    a = _item(viewer, followed, reason="follow", minutes_ago=1)
    b = _item(viewer, friend_followed, reason="friend", minutes_ago=2)
    _item(viewer, friend_only, reason="friend", minutes_ago=3)
    _item(viewer, viewer, reason="self", minutes_ago=4)
    c = _item(viewer, page, reason="follow", minutes_ago=5)
    _deliver(
        _event(
            "user.followed", {"follower": viewer, "target": friend_followed, "target_type": "user"}
        )
    )
    _deliver(_event("user.followed", {"follower": viewer, "target": page, "target_type": "page"}))
    assert _all(client_for(viewer), "following") == [str(a.post_id), str(b.post_id), str(c.post_id)]
    assert FollowEdge.objects.get(follower_id=viewer, target_id=page).target_type == "page"

    _deliver(
        _event(
            "user.unfollowed",
            {"follower": viewer, "target": friend_followed, "target_type": "user"},
        )
    )
    assert str(b.post_id) not in _all(client_for(viewer), "following")
    # The friend item itself stays in the feed (unfollow drops follow items only).
    assert str(b.post_id) in _all(client_for(viewer), "recent")


def test_a_muted_author_leaves_the_muters_feed_in_every_mode(client_for):
    viewer, muted, other = _acct(), _acct(), _acct()
    _item(viewer, muted)
    kept = _item(viewer, other)
    RelationshipFlag.objects.create(
        actor_id=viewer, target_id=muted, kind="favorite", occurred_at=timezone.now()
    )
    t = timezone.now()
    _deliver(
        _event(
            "relationship.muted",
            {"actor_id": viewer, "target_id": muted, "occurred_at": t.isoformat()},
        )
    )
    for mode in ("recent", "for_you", "following"):
        assert _all(client_for(viewer), mode) == [str(kept.post_id)], mode
    assert _all(client_for(viewer), "favorites") == []
    # The muted author's own feed is untouched.
    _item(muted, viewer)
    assert len(_all(client_for(muted), "recent")) == 1

    # A retried older unmute changes nothing; a newer one restores the posts.
    old = (t - timedelta(minutes=1)).isoformat()
    _deliver(
        _event("relationship.unmuted", {"actor_id": viewer, "target_id": muted, "occurred_at": old})
    )
    assert len(_all(client_for(viewer), "recent")) == 1
    new = (t + timedelta(minutes=1)).isoformat()
    _deliver(
        _event("relationship.unmuted", {"actor_id": viewer, "target_id": muted, "occurred_at": new})
    )
    assert len(_all(client_for(viewer), "recent")) == 2


def test_relationship_consumers_are_idempotent():
    actor, target = _acct(), _acct()
    event = _event(
        "relationship.muted",
        {"actor_id": actor, "target_id": target, "occurred_at": timezone.now().isoformat()},
    )
    _deliver(event)
    _deliver(event)
    handlers.on_relationship_muted(event)  # even without the worker's guard
    assert RelationshipFlag.objects.filter(actor_id=actor, target_id=target).count() == 1


# ---- ranking ------------------------------------------------------------------


def test_ranked_mode_returns_the_same_order_for_the_same_fixtures():
    viewer = _acct()
    authors = [_acct() for _ in range(3)]
    for i in range(15):
        _item(viewer, authors[i % 3], minutes_ago=i * 30, reason=["friend", "follow"][i % 2])
    now = timezone.now()
    first = [str(i.id) for i in ranking.rank_items(viewer, now)]
    second = [str(i.id) for i in ranking.rank_items(viewer, now)]
    assert first == second
    assert len(first) == 15


def test_page_two_has_no_duplicates_after_5_new_posts(client_for, monkeypatch):
    viewer, author = _acct(), _acct()
    old = {str(_item(viewer, author, minutes_ago=10 + i).post_id) for i in range(25)}
    client = client_for(viewer)
    body = client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 10}).json()
    page1 = [i["post_id"] for i in body["data"]]

    # Five new posts arrive through the normal fan-out.
    monkeypatch.setattr(
        "feed.services.fanout_audience",
        lambda a: {"followers": [viewer], "friends": [], "recipients": [viewer]},
    )
    for _ in range(5):
        services.fan_out_post(
            {
                "post_id": str(uuid.uuid4()),
                "author_id": author,
                "audience": "public",
                "excerpt": "new",
                "created_at": timezone.now().isoformat(),
            }
        )

    seen = list(page1)
    cursor = body["page"]["next_cursor"]
    while cursor:
        body = client.get(
            reverse("feed:home-feed"), {"mode": "for_you", "limit": 10, "cursor": cursor}
        ).json()
        assert body["page"]["fallback"] is False
        seen += [i["post_id"] for i in body["data"]]
        cursor = body["page"]["next_cursor"]
    assert len(seen) == len(set(seen)) == 25
    assert set(seen) == old  # the new posts wait for the next first page
    first = client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 5}).json()
    assert {i["post_id"] for i in first["data"]}.isdisjoint(old)


def test_cursor_is_signed_and_opaque(client_for, world):
    viewer, _, _ = world
    client = client_for(viewer)
    body = client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 5}).json()
    cursor = body["page"]["next_cursor"]
    assert viewer not in cursor
    tampered = cursor[:-2] + ("A" if cursor[-2] != "A" else "B") + cursor[-1]
    resp = client.get(reverse("feed:home-feed"), {"mode": "for_you", "cursor": tampered})
    assert resp.status_code == 404
    resp = client.get(reverse("feed:home-feed"), {"mode": "for_you", "cursor": "garbage"})
    assert resp.status_code == 404


def test_a_lost_session_falls_back_to_latest_order(client_for, world):
    viewer, author, items = world
    client = client_for(viewer)
    body = client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 5}).json()
    cursor = body["page"]["next_cursor"]
    caches["hot"].clear()  # expired, evicted or redis-hot restarted
    newer = _item(viewer, author, minutes_ago=-1)

    body = client.get(
        reverse("feed:home-feed"), {"mode": "for_you", "limit": 5, "cursor": cursor}
    ).json()
    assert body["page"]["fallback"] is True
    expected = [
        str(i.post_id) for i in sorted(items, key=lambda i: i.post_created_at, reverse=True)
    ]
    assert [i["post_id"] for i in body["data"]] == expected[:5]
    assert str(newer.post_id) not in [i["post_id"] for i in body["data"]]
    # The fallback goes on page by page in latest order to the end.
    rest = []
    cursor = body["page"]["next_cursor"]
    while cursor:
        body = client.get(
            reverse("feed:home-feed"), {"mode": "for_you", "limit": 5, "cursor": cursor}
        ).json()
        rest += [i["post_id"] for i in body["data"]]
        cursor = body["page"]["next_cursor"]
    assert rest == expected[5:]


def test_a_newer_first_page_replaces_the_session(client_for, world):
    viewer, _, _ = world
    client = client_for(viewer)
    old = client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 5}).json()
    client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 5})
    body = client.get(
        reverse("feed:home-feed"),
        {"mode": "for_you", "limit": 5, "cursor": old["page"]["next_cursor"]},
    ).json()
    assert body["page"]["fallback"] is True


def test_redis_hot_down_still_serves_for_you(client_for, world, monkeypatch):
    viewer, _, _ = world

    class _Down:
        def set(self, *a, **k):
            raise ConnectionError("redis-hot down")

        def get(self, *a, **k):
            raise ConnectionError("redis-hot down")

    monkeypatch.setattr("feed.ranking._hot", lambda: _Down())
    client = client_for(viewer)
    body = client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 5}).json()
    assert len(body["data"]) == 5
    assert body["page"]["fallback"] is True
    seen = [i["post_id"] for i in body["data"]]
    cursor = body["page"]["next_cursor"]
    while cursor:
        body = client.get(
            reverse("feed:home-feed"), {"mode": "for_you", "limit": 5, "cursor": cursor}
        ).json()
        seen += [i["post_id"] for i in body["data"]]
        cursor = body["page"]["next_cursor"]
    assert len(set(seen)) == 12  # repeats are possible, a missing post is not


def test_rows_beyond_the_window_follow_in_latest_order(client_for, settings):
    settings.FEED_RANK_WINDOW = 5
    viewer, author = _acct(), _acct()
    items = [_item(viewer, author, minutes_ago=i) for i in range(12)]
    pages, _ = _pages(client_for(viewer), "for_you", limit=3)
    seen = [p for page in pages for p in page]
    assert len(seen) == len(set(seen)) == 12
    assert set(seen[:5]) == {str(i.post_id) for i in items[:5]}
    assert seen[5:] == [str(i.post_id) for i in items[5:]]


def test_hiding_between_pages_drops_the_post_from_the_session(client_for, world):
    viewer, _, items = world
    client = client_for(viewer)
    body = client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 5}).json()
    page1 = [i["post_id"] for i in body["data"]]
    later = next(str(i.post_id) for i in items if str(i.post_id) not in page1)
    client.post(reverse("feed:hide"), {"post_id": later, "reason": "other"})
    rest = []
    cursor = body["page"]["next_cursor"]
    while cursor:
        body = client.get(
            reverse("feed:home-feed"), {"mode": "for_you", "limit": 5, "cursor": cursor}
        ).json()
        rest += [i["post_id"] for i in body["data"]]
        cursor = body["page"]["next_cursor"]
    assert later not in rest
    assert len(page1) + len(rest) == 11


def test_engagement_events_raise_the_post(client_for):
    viewer, author, reactor = _acct(), _acct(), _acct()
    plain = _item(viewer, author, minutes_ago=1)
    engaged = _item(viewer, author, minutes_ago=30)
    pid = str(engaged.post_id)
    reacted = _event(
        "post.reacted",
        {"post_id": pid, "reactor": reactor, "reaction_type": "like", "author_id": author},
    )
    _deliver(reacted)
    _deliver(reacted)  # a redelivery counts once
    for _ in range(3):
        _deliver(
            _event(
                "post.commented",
                {"post_id": pid, "author": reactor, "post_author_id": author, "comment_id": "c"},
            )
        )
    _deliver(_event("post.shared", {"post_id": pid, "sharer": reactor, "author_id": author}))
    stats = PostStats.objects.get(post_id=pid)
    assert (stats.reactions, stats.comments, stats.shares) == (1, 3, 1)
    engaged.refresh_from_db()
    plain.refresh_from_db()
    assert engaged.score > 0 and plain.score == 0
    assert _all(client_for(viewer), "for_you")[0] == pid
    assert _all(client_for(viewer), "recent")[0] == str(plain.post_id)

    _deliver(
        _event(
            "post.unreacted",
            {"post_id": pid, "reactor": reactor, "reaction_type": "like", "author_id": author},
        )
    )
    assert PostStats.objects.get(post_id=pid).reactions == 0
    assert Affinity.objects.get(account_id=reactor, author_id=author).interactions == 4


def test_engagement_counted_before_the_fan_out_is_kept(monkeypatch):
    author, viewer = _acct(), _acct()
    pid = str(uuid.uuid4())
    _deliver(
        _event(
            "post.reacted",
            {"post_id": pid, "reactor": viewer, "reaction_type": "like", "author_id": author},
        )
    )
    monkeypatch.setattr(
        "feed.services.fanout_audience",
        lambda a: {"followers": [viewer], "friends": [], "recipients": [viewer]},
    )
    services.fan_out_post(
        {
            "post_id": pid,
            "author_id": author,
            "audience": "public",
            "created_at": timezone.now().isoformat(),
        }
    )
    assert all(i.score > 0 for i in FeedItem.objects.filter(post_id=pid))


def test_affinity_lifts_an_author_the_viewer_interacts_with():
    viewer, close, distant = _acct(), _acct(), _acct()
    c = _item(viewer, close, minutes_ago=60)
    d = _item(viewer, distant, minutes_ago=50)
    now = timezone.now()
    assert [i.id for i in ranking.rank_items(viewer, now)] == [d.id, c.id]
    for _ in range(6):
        _deliver(
            _event(
                "post.reacted",
                {
                    "post_id": str(uuid.uuid4()),
                    "reactor": viewer,
                    "reaction_type": "like",
                    "author_id": close,
                },
            )
        )
    assert [i.id for i in ranking.rank_items(viewer, now)] == [c.id, d.id]


def test_own_reactions_do_not_build_affinity():
    me = _acct()
    _deliver(
        _event(
            "post.reacted",
            {"post_id": str(uuid.uuid4()), "reactor": me, "reaction_type": "like", "author_id": me},
        )
    )
    assert not Affinity.objects.exists()


def test_cold_start_is_close_to_chronological():
    viewer = _acct()
    items = [_item(viewer, _acct(), minutes_ago=i * 120) for i in range(6)]
    ranked = ranking.rank_items(viewer, timezone.now())
    assert [i.id for i in ranked] == [i.id for i in items]


def test_block_forgets_affinity_and_favorites():
    a, b = _acct(), _acct()
    Affinity.objects.create(account_id=a, author_id=b, interactions=5)
    RelationshipFlag.objects.create(
        actor_id=a, target_id=b, kind="favorite", occurred_at=timezone.now()
    )
    _item(a, b)
    _deliver(_event("user.blocked", {"blocker_id": b, "blocked_id": a}))
    assert not Affinity.objects.exists()
    assert not RelationshipFlag.objects.filter(active=True).exists()
    assert not FeedItem.objects.exists()


def test_non_searchable_authors_still_reach_their_own_connections(client_for):
    viewer, author = _acct(), _acct()
    item = _item(viewer, author, reason="follow")
    _deliver(_event("profile.updated", {"handle": "x", "searchable": False}, subject=author))
    assert AuthorRef.objects.get(account_id=author).searchable is False
    # A follower is connected: this is not a recommendation, so it stays.
    assert _all(client_for(viewer), "for_you") == [str(item.post_id)]
    # for_you draws only from the viewer's own connections.
    assert set(FeedItem.objects.values_list("reason", flat=True)) <= set(ranking.CONNECTED)

    # A profile.updated without the flag (pre-1.6) changes nothing.
    _deliver(_event("profile.updated", {"handle": "y"}, subject=author))
    assert AuthorRef.objects.get(account_id=author).searchable is False


def test_for_you_keeps_non_public_items_as_ids_only(client_for):
    viewer, author = _acct(), _acct()
    _item(viewer, author, audience="friends", reason="friend")
    item = client_for(viewer).get(reverse("feed:home-feed"), {"mode": "for_you"}).json()["data"][0]
    assert "excerpt" not in item["snapshot"]
    assert set(item["snapshot"]) <= set(services._ID_KEYS)


def test_for_you_never_returns_another_viewers_rows(client_for):
    a, b, author = _acct(), _acct(), _acct()
    for i in range(3):
        _item(a, author, minutes_ago=i + 1)
    mine = _item(b, author, minutes_ago=5)
    assert _all(client_for(b), "for_you") == [str(mine.post_id)]
    # A cursor minted for a's session gives b nothing but b's own rows.
    cursor = (
        client_for(a)
        .get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 1})
        .json()["page"]["next_cursor"]
    )
    body = (
        client_for(b).get(reverse("feed:home-feed"), {"mode": "for_you", "cursor": cursor}).json()
    )
    assert body["page"]["fallback"] is True
    assert [i["post_id"] for i in body["data"]] == [str(mine.post_id)]


def test_sponsored_slot_on_the_first_page_of_every_mode(client_for, world, monkeypatch):
    viewer, _, _ = world
    monkeypatch.setattr(
        "feed.ads_client.feed_sponsored", lambda v: {"creative_id": "c1", "sponsored": True}
    )
    client = client_for(viewer)
    for mode in MODES:
        body = client.get(reverse("feed:home-feed"), {"mode": mode, "limit": 5}).json()
        assert body["sponsored"]["creative_id"] == "c1", mode
        nxt = client.get(
            reverse("feed:home-feed"),
            {"mode": mode, "limit": 5, "cursor": body["page"]["next_cursor"]},
        ).json()
        assert "sponsored" not in nxt, mode


def test_a_favorite_ranks_above_fresher_posts_in_for_you():
    viewer, fav, other = _acct(), _acct(), _acct()
    older = _item(viewer, fav, minutes_ago=12 * 60)
    fresh = _item(viewer, other, minutes_ago=1)
    now = timezone.now()
    assert [i.id for i in ranking.rank_items(viewer, now)] == [fresh.id, older.id]
    _deliver(
        _event(
            "relationship.favorited",
            {"actor_id": viewer, "target_id": fav, "occurred_at": now.isoformat()},
        )
    )
    assert [i.id for i in ranking.rank_items(viewer, now)] == [older.id, fresh.id]
