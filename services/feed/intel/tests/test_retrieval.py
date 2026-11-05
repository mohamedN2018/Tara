"""WP 3.4: candidate sources. Group posts reach members, capped authors reach every
follower through pull, a new follow brings the last 7 days, and no pulled item
duplicates a feed row the viewer already has."""

import uuid
from datetime import timedelta

import pytest
from feed import services
from feed.models import FeedItem, FollowEdge

from intel import config, retrieval
from intel.models import FanoutCapped, MediaRef
from intel.retrieval import sources

from . import world as w

pytestmark = pytest.mark.django_db
HOME = config.for_surface("home")


def ids(items, source=None):
    return {c.post_id for c in items if source is None or c.source == source}


def home(viewer, cfg=HOME):
    return retrieval.candidates(viewer, "home", cfg, now=w.NOW)


# ---- groups (D1) --------------------------------------------------------------------


def test_group_posts_of_joined_groups_appear_in_home_candidates():
    viewer, author = w.uid(), w.uid()
    joined, other = w.group(privacy="private"), w.group()
    w.member(viewer, joined, notify=True)
    approved = w.post(author, audience="group", group=joined)
    pending = w.post(author, audience="group", group=joined, approval="pending")
    elsewhere = w.post(author, audience="group", group=other)
    old = w.post(author, audience="group", group=joined, age=timedelta(days=31))

    found = home(viewer)
    assert ids(found, "groups") == {approved}
    assert {c.reason for c in found if c.source == "groups"} == {"group_notify"}
    assert not {pending, elsewhere, old} & ids(found)


def test_left_and_banned_members_get_no_group_posts():
    viewer, author = w.uid(), w.uid()
    g = w.group()
    w.post(author, audience="group", group=g)
    for state in ("none", "banned", "requested"):
        w.member(viewer, g, state=state)
        assert not ids(home(viewer), "groups")


# ---- follow_pull (D2: capped fan-out) ---------------------------------------------------


@pytest.fixture
def capped_author(settings, monkeypatch):
    """An author with 5,001 followers, fanned out with FANOUT_MAX_RECIPIENTS=5."""
    settings.FANOUT_MAX_RECIPIENTS = 5
    author = w.uid()
    followers = [str(uuid.uuid4()) for _ in range(5001)]
    FollowEdge.objects.bulk_create(
        [
            FollowEdge(follower_id=f, target_id=author, occurred_at=w.NOW - timedelta(days=30))
            for f in followers
        ]
    )
    monkeypatch.setattr(
        services, "fanout_audience", lambda a, **kw: {"friends": [], "followers": followers}
    )
    post_id = w.post(author, age=timedelta(hours=2))
    services.fan_out_post(
        {
            "post_id": post_id,
            "author_id": author,
            "author_type": "user",
            "type": "text",
            "audience": "public",
            "excerpt": "hi",
            "created_at": (w.NOW - timedelta(hours=2)).isoformat(),
        }
    )
    return author, followers, post_id


def test_a_capped_author_reaches_every_follower_through_pull(capped_author):
    author, followers, post_id = capped_author
    assert FanoutCapped.objects.filter(post_id=post_id).count() == 1
    fanned = {
        str(r)
        for r in FeedItem.objects.filter(post_id=post_id).values_list("recipient_id", flat=True)
    }
    assert len(fanned) == 5 and author in fanned
    # Every follower, sampled across the whole list (the query is the same for each).
    sample = followers[:10] + followers[::97] + followers[-10:]
    for viewer in sample:
        found = [c for c in home(viewer) if c.post_id == post_id]
        assert len(found) == 1, viewer
        expected = "connections" if viewer in fanned else "follow_pull"
        assert found[0].source == expected
        if expected == "follow_pull":
            assert found[0].reason == "capped"


def test_capped_posts_are_pulled_only_for_connections_and_within_the_window():
    author, follower, stranger, friend = w.uid(), w.uid(), w.uid(), w.uid()
    w.follow(follower, author)
    w.friends(friend, author)
    recent = w.post(author, age=timedelta(days=2))
    old = w.post(author, age=timedelta(days=8))  # capped_days = 7
    w.capped(recent, author)
    w.capped(old, author)
    assert ids(home(follower), "follow_pull") == {recent}
    assert ids(home(friend), "follow_pull") == {recent}
    assert not ids(home(stranger), "follow_pull")


def test_no_pulled_item_duplicates_a_feed_row_the_viewer_has():
    author, viewer = w.uid(), w.uid()
    w.follow(viewer, author, at=w.NOW - timedelta(hours=1))  # also a new follow
    have = w.post(author, age=timedelta(hours=3))
    hidden = w.post(author, age=timedelta(hours=4))
    w.capped(have, author)
    w.capped(hidden, author)
    w.feed_row(viewer, have, author, "follow")
    w.feed_row(viewer, hidden, author, "follow")
    w.hide(viewer, hidden, author)  # hidden: never back through a pull source

    found = home(viewer)
    assert [c.source for c in found if c.post_id == have] == ["connections"]
    assert hidden not in ids(found)
    assert len(found) == len(ids(found))
    for source in (sources.follow_pull, sources.groups):
        assert not {have, hidden} & ids(source(viewer, HOME, w.NOW))


# ---- follow_pull (D3: new follows) -----------------------------------------------------


def test_a_new_follow_shows_the_last_seven_days():
    author, viewer, old_follower = w.uid(), w.uid(), w.uid()
    w.follow(viewer, author, at=w.NOW - timedelta(hours=2))
    w.follow(old_follower, author, at=w.NOW - timedelta(hours=30))  # new_follow_hours = 24
    day3 = w.post(author, age=timedelta(days=3))
    day6 = w.post(author, age=timedelta(days=6, hours=23))
    day8 = w.post(author, age=timedelta(days=8))
    gone = w.post(author, age=timedelta(days=1), state="deleted")

    found = home(viewer)
    assert ids(found, "follow_pull") == {day3, day6}
    assert {c.reason for c in found if c.source == "follow_pull"} == {"new_follow"}
    assert not {day8, gone} & ids(found)
    assert not ids(home(old_follower), "follow_pull")


def test_a_new_friend_counts_as_a_new_follow():
    author, viewer = w.uid(), w.uid()
    w.friends(viewer, author, since=w.NOW - timedelta(hours=1))
    p = w.post(author, audience="friends", age=timedelta(days=2))
    assert ids(home(viewer), "follow_pull") == {p}


def test_windows_come_from_the_config():
    author, viewer = w.uid(), w.uid()
    w.follow(viewer, author, at=w.NOW - timedelta(hours=2))
    posts = [w.post(author, age=timedelta(hours=h + 1)) for h in range(5)]
    cfg = config.for_surface("home", {"window": {"follow_pull": 2}})
    assert ids(home(viewer, cfg), "follow_pull") == set(posts[:2])


# ---- reels and video -------------------------------------------------------------------


def test_reels_surface_has_connected_and_public_published_reels():
    viewer, friend, stranger = w.uid(), w.uid(), w.uid()
    connected = w.post(friend, type="reel", audience="friends")
    w.feed_row(viewer, connected, friend, type="reel")
    public = w.post(stranger, type="reel")
    friends_only = w.post(stranger, type="reel", audience="friends")
    old = w.post(stranger, type="reel", age=timedelta(days=8))  # pools.window_days = 7
    w.post(stranger, type="video")
    landscape_media, long_media = str(uuid.uuid4()), str(uuid.uuid4())
    MediaRef.objects.create(media_id=landscape_media, width=1280, height=720, updated_at=w.NOW)
    MediaRef.objects.create(
        media_id=long_media, width=720, height=1280, duration_ms=120_000, updated_at=w.NOW
    )
    landscape = w.post(stranger, type="reel", media_ids=[landscape_media])
    too_long = w.post(stranger, type="reel", media_ids=[long_media])

    found = retrieval.candidates(viewer, "reels", now=w.NOW)
    assert ids(found, "connections") == {connected}
    assert ids(found, "reels") == {public}
    assert not {friends_only, old, landscape, too_long} & ids(found)


def test_video_surface_has_connected_and_public_videos():
    viewer, friend, stranger = w.uid(), w.uid(), w.uid()
    connected = w.post(friend, type="video", audience="friends")
    w.feed_row(viewer, connected, friend, type="video")
    public = w.post(stranger, type="video")
    in_group = w.post(stranger, type="video", audience="group", group=w.group())
    found = retrieval.candidates(viewer, "video", now=w.NOW)
    assert ids(found, "connections") == {connected}
    assert ids(found, "video") == {public}
    assert in_group not in ids(found)


def test_every_candidate_is_found_once_with_its_first_source():
    author, viewer = w.uid(), w.uid()
    g = w.group()
    w.member(viewer, g)
    w.follow(viewer, author, at=w.NOW - timedelta(hours=1))
    p = w.post(author, audience="group", group=g)
    found = home(viewer)
    assert [c.source for c in found if c.post_id == p] == ["follow_pull"]
