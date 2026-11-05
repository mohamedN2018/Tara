"""Reels (roadmap 5.5 / 5.8): what may be a reel, who sees it, the feeds, views."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from posts.models import BlockedPair, OutboxEvent, Post, PostReaction

from reels.models import Reel, ReelView

from .conftest import acct, add_video

pytestmark = pytest.mark.django_db


def _create(client, **data):
    return client.post(reverse("reels:reel-list"), data, format="json")


def _code(resp) -> str:
    return resp.json()["error"]["code"]


def _feed(client, **params):
    resp = client.get(reverse("reels:reel-list"), params)
    assert resp.status_code == 200, resp.content
    return [item["id"] for item in resp.json()["data"]]


def _reel(client_for, media_stub, author=None, **data) -> str:
    author = author or acct()
    clip = add_video(media_stub, author)
    resp = _create(client_for(author), media_id=clip, **data)
    assert resp.status_code == 201, resp.content
    return resp.json()["data"]["id"]


# ---- what can be a reel --------------------------------------------------------------


def test_a_short_vertical_video_becomes_a_reel(client_for, media_stub):
    author = acct()
    clip = add_video(media_stub, author, width=1080, height=1920, duration_ms=30_000)
    resp = _create(client_for(author), media_id=clip, caption="  first #reel  ", audience="friends")
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert (
        data["type"] == "reel" and data["body"] == "first #reel" and data["audience"] == "friends"
    )
    assert data["reel"]["media_id"] == clip
    assert (data["reel"]["width"], data["reel"]["height"], data["reel"]["duration_ms"]) == (
        1080,
        1920,
        30_000,
    )
    assert data["reel"]["view_count"] == 0
    post = Post.objects.get()
    reel = Reel.objects.get()
    assert (
        reel.post_id == post.id
        and str(reel.author_id) == author
        and reel.created_at == post.created_at
    )
    # The post pipeline did the rest: media bound restricted, tags, the fan-out event.
    assert media_stub.binds[-1] == {
        "owner_id": author,
        "post_id": str(post.id),
        "ids": [clip],
        "restricted": True,
    }
    assert {h.hashtag.tag for h in post.hashtags.all()} == {"reel"}
    event = OutboxEvent.objects.get(event_type="post.created").payload
    assert event["payload"]["type"] == "reel" and event["payload"]["media_ids"] == [clip]


@pytest.mark.parametrize(
    ("width", "height", "duration_ms", "code"),
    [
        (1280, 720, 15_000, "reel_not_vertical"),  # landscape
        (1080, 1080, 15_000, "reel_not_vertical"),  # square
        (1080, 1350, 15_000, "reel_not_vertical"),  # 4:5 is not 9:16
        (720, 1280, 90_001, "reel_too_long"),
        (720, 1280, 5 * 60_000, "reel_too_long"),
    ],
)
def test_landscape_or_long_videos_are_refused_as_reels(
    client_for, media_stub, width, height, duration_ms, code
):
    author = acct()
    clip = add_video(media_stub, author, width=width, height=height, duration_ms=duration_ms)
    resp = _create(client_for(author), media_id=clip)
    assert resp.status_code == 400
    assert _code(resp) == code
    assert not Post.objects.exists() and not Reel.objects.exists()
    assert media_stub.binds == []  # nothing bound: it can still be a normal video post
    # ... and it still can.
    as_video = client_for(author).post(
        reverse("posts:post-create"),
        {"type": "video", "media_ids": [clip], "body": "v"},
        format="json",
    )
    assert as_video.status_code == 201, as_video.content


def test_ninety_seconds_and_tall_phones_are_still_reels(client_for, media_stub):
    author = acct()
    for width, height, duration in ((720, 1280, 90_000), (886, 1920, 20_000), (720, 1080, 10_000)):
        clip = add_video(media_stub, author, width=width, height=height, duration_ms=duration)
        assert _create(client_for(author), media_id=clip).status_code == 201


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"status": "processing"}, "reel_video_not_ready"),
        ({"status": "failed"}, "reel_video_not_ready"),
        ({"purpose": ""}, "reel_video_required"),  # a chat video, never transcoded
        ({"width": None}, "reel_video_not_ready"),  # not measured yet
    ],
)
def test_the_video_must_be_transcoded_and_ready(client_for, media_stub, kw, code):
    author = acct()
    clip = add_video(media_stub, author, **kw)
    resp = _create(client_for(author), media_id=clip)
    assert resp.status_code == 400 and _code(resp) == code


def test_someone_elses_or_unknown_media_reads_as_not_found(client_for, media_stub):
    clip = add_video(media_stub, acct())
    me = client_for(acct())
    assert _code(_create(me, media_id=clip)) == "media_not_owned"
    assert _code(_create(me, media_id=str(acct()))) == "media_not_owned"
    image = media_stub.add(acct())
    assert _code(_create(me, media_id=image)) == "media_not_owned"


def test_one_video_is_one_reel(client_for, media_stub):
    author = acct()
    clip = add_video(media_stub, author)
    assert _create(client_for(author), media_id=clip).status_code == 201
    again = _create(client_for(author), media_id=clip)
    assert again.status_code == 400 and _code(again) == "media_already_attached"
    assert Reel.objects.count() == 1


def test_group_audience_is_not_offered(client_for, media_stub):
    author = acct()
    resp = _create(client_for(author), media_id=add_video(media_stub, author), audience="group")
    assert resp.status_code == 400


def test_a_cover_photo_is_bound_restricted_to_the_reel(client_for, media_stub):
    author = acct()
    clip = add_video(media_stub, author)
    cover = media_stub.add(author, kind="image")
    resp = _create(client_for(author), media_id=clip, cover_media_id=cover, audience="public")
    assert resp.status_code == 201, resp.content
    post_id = resp.json()["data"]["id"]
    assert resp.json()["data"]["reel"]["cover_media_id"] == cover
    cover_bind = next(b for b in media_stub.binds if b["ids"] == [cover])
    # Always restricted: it follows the post's visibility, whatever the audience becomes.
    assert cover_bind == {
        "owner_id": author,
        "post_id": post_id,
        "ids": [cover],
        "restricted": True,
    }
    # A cover is a photo, and the author's own.
    other = add_video(media_stub, author)
    assert (
        _code(_create(client_for(author), media_id=other, cover_media_id=other))
        == "reel_cover_invalid"
    )
    strangers = media_stub.add(acct(), kind="image")
    assert (
        _code(_create(client_for(author), media_id=other, cover_media_id=strangers))
        == "media_not_owned"
    )


def test_eligibility_tells_the_composer_reel_or_video(client_for, media_stub):
    author = acct()
    me = client_for(author)
    url = reverse("reels:reel-eligibility")
    vertical = add_video(media_stub, author)
    landscape = add_video(media_stub, author, width=1920, height=1080)
    ok = me.post(url, {"media_id": vertical}, format="json").json()["data"]
    assert ok["eligible"] is True and ok["code"] is None and ok["max_duration_ms"] == 90_000
    no = me.post(url, {"media_id": landscape}, format="json").json()["data"]
    assert no == {
        "media_id": landscape,
        "eligible": False,
        "code": "reel_not_vertical",
        "duration_ms": 15_000,
        "width": 1920,
        "height": 1080,
        "max_duration_ms": 90_000,
    }
    # Someone else's video: no measures leak.
    theirs = client_for(acct()).post(url, {"media_id": vertical}, format="json").json()["data"]
    assert (
        theirs["eligible"] is False
        and theirs["code"] == "media_not_owned"
        and theirs["width"] is None
    )


# ---- who sees a reel -----------------------------------------------------------------


def test_detail_follows_the_post_audience_and_hides_with_404(client_for, media_stub, graph):
    author, friend, stranger = acct(), acct(), acct()
    graph.befriend(author, friend)
    reel_id = _reel(client_for, media_stub, author, audience="friends")
    url = reverse("reels:reel-detail", args=[reel_id])
    assert client_for(friend).get(url).status_code == 200
    assert client_for(stranger).get(url).status_code == 404
    assert client_for(author).get(url).status_code == 200
    # A normal post is not a reel.
    post = client_for(author).post(reverse("posts:post-create"), {"body": "hi"}, format="json")
    assert (
        client_for(author)
        .get(reverse("reels:reel-detail", args=[post.json()["data"]["id"]]))
        .status_code
        == 404
    )


def test_blocked_deleted_and_removed_reels_are_gone(client_for, media_stub):
    author, viewer = acct(), acct()
    reel_id = _reel(client_for, media_stub, author)
    url = reverse("reels:reel-detail", args=[reel_id])
    assert client_for(viewer).get(url).status_code == 200
    block = BlockedPair.objects.create(blocker_id=author, blocked_id=viewer)
    assert client_for(viewer).get(url).status_code == 404
    assert reel_id not in _feed(client_for(viewer))
    block.delete()
    Post.objects.filter(id=reel_id).update(moderation_status=Post.ModerationStatus.REMOVED)
    assert client_for(viewer).get(url).status_code == 404
    assert reel_id not in _feed(client_for(viewer))
    Post.objects.filter(id=reel_id).update(moderation_status=Post.ModerationStatus.OK)
    assert (
        client_for(author).delete(reverse("posts:post-detail", args=[reel_id])).status_code == 204
    )
    assert client_for(viewer).get(url).status_code == 404
    assert client_for(author).get(url).status_code == 404


# ---- feeds ---------------------------------------------------------------------------


def test_for_you_mixes_public_friends_and_followed_and_skips_own(client_for, media_stub, graph):
    me, friend, followed, stranger = acct(), acct(), acct(), acct()
    graph.befriend(me, friend)
    graph.follow(me, followed)
    public = _reel(client_for, media_stub, stranger, audience="public")
    strangers_friends_only = _reel(client_for, media_stub, stranger, audience="friends")
    friends_only = _reel(client_for, media_stub, friend, audience="friends")
    followers_only = _reel(client_for, media_stub, followed, audience="followers")
    mine = _reel(client_for, media_stub, me)
    only_me = _reel(client_for, media_stub, friend, audience="only_me")
    ids = _feed(client_for(me))
    assert ids == [followers_only, friends_only, public]  # newest first
    assert strangers_friends_only not in ids and mine not in ids and only_me not in ids
    # Following: friends and followed accounts only.
    assert _feed(client_for(me), tab="following") == [followers_only, friends_only]
    assert (
        _code(client_for(me).get(reverse("reels:reel-list"), {"tab": "nope"})) == "validation_error"
    )


def test_graph_down_leaves_public_reels_only(client_for, media_stub, graph):
    me, friend = acct(), acct()
    graph.befriend(me, friend)
    public = _reel(client_for, media_stub, friend, audience="public")
    _reel(client_for, media_stub, friend, audience="friends")
    graph.down = True
    assert _feed(client_for(me)) == [public]
    assert _feed(client_for(me), tab="following") == []


def test_muted_and_not_interested_leave_the_feeds(client_for, media_stub, graph):
    me, muted, other = acct(), acct(), acct()
    graph.mute(me, muted)
    _reel(client_for, media_stub, muted)
    keep = _reel(client_for, media_stub, other)
    dull = _reel(client_for, media_stub, other)
    viewer = client_for(me)
    assert _feed(viewer) == [dull, keep]
    hide = reverse("reels:reel-hide", args=[dull])
    assert viewer.post(hide).status_code == 204
    assert viewer.post(hide).status_code == 204  # idempotent
    assert _feed(viewer) == [keep]
    # Still reachable by link and on the profile; undo brings it back.
    assert viewer.get(reverse("reels:reel-detail", args=[dull])).status_code == 200
    assert viewer.delete(hide).status_code == 204
    assert _feed(viewer) == [dull, keep]
    # Not your own.
    mine = _reel(client_for, media_stub, me)
    assert _code(viewer.post(reverse("reels:reel-hide", args=[mine]))) == "reel_own"


def test_profile_reels_tab_shows_what_the_viewer_may_see(client_for, media_stub, graph):
    author, friend, stranger, blocked = acct(), acct(), acct(), acct()
    graph.befriend(author, friend)
    public = _reel(client_for, media_stub, author, audience="public")
    friends_only = _reel(client_for, media_stub, author, audience="friends")
    # A normal video post never shows in the Reels tab.
    clip = add_video(media_stub, author, width=1920, height=1080)
    client_for(author).post(
        reverse("posts:post-create"), {"type": "video", "media_ids": [clip]}, format="json"
    )
    BlockedPair.objects.create(blocker_id=blocked, blocked_id=author)
    assert _feed(client_for(author), author_id=author) == [friends_only, public]
    assert _feed(client_for(friend), author_id=author) == [friends_only, public]
    assert _feed(client_for(stranger), author_id=author) == [public]
    assert _feed(client_for(blocked), author_id=author) == []


def test_reels_stay_out_of_the_videos_list(client_for, media_stub):
    author = acct()
    reel_id = _reel(client_for, media_stub, author)
    clip = add_video(media_stub, author, width=1920, height=1080, duration_ms=300_000)
    video = client_for(author).post(
        reverse("posts:post-create"), {"type": "video", "media_ids": [clip]}, format="json"
    )
    listed = client_for(acct()).get(reverse("posts:post-create"), {"type": "video"}).json()["data"]
    assert [p["id"] for p in listed] == [video.json()["data"]["id"]]
    assert reel_id not in [p["id"] for p in listed]


# ---- reactions, comments, views ------------------------------------------------------


def test_likes_and_comments_are_the_posts(client_for, media_stub):
    author, viewer = acct(), acct()
    reel_id = _reel(client_for, media_stub, author)
    me = client_for(viewer)
    assert me.post(
        reverse("posts:post-reactions", args=[reel_id]), {"type": "like"}, format="json"
    ).status_code in (200, 201)
    assert (
        me.post(
            reverse("posts:post-comments", args=[reel_id]), {"body": "nice"}, format="json"
        ).status_code
        == 201
    )
    data = me.get(reverse("reels:reel-detail", args=[reel_id])).json()["data"]
    assert (
        data["my_reaction"] == "like" and data["reaction_count"] == 1 and data["comment_count"] == 1
    )
    assert PostReaction.objects.filter(post_id=reel_id).count() == 1


def test_views_count_once_per_viewer_per_day_never_the_author(client_for, media_stub, graph):
    author, viewer, stranger = acct(), acct(), acct()
    graph.befriend(author, viewer)
    reel_id = _reel(client_for, media_stub, author, audience="friends")
    url = reverse("reels:reel-view", args=[reel_id])
    watched = {"watch_ms": 1500}  # D12: at least 1 s of play
    first = client_for(viewer).post(url, watched, format="json").json()["data"]
    assert first == {"view_count": 1, "counted": True}
    again = client_for(viewer).post(url, watched, format="json").json()["data"]
    assert again == {"view_count": 1, "counted": False}
    mine = client_for(author).post(url, watched, format="json").json()["data"]
    assert mine == {"view_count": 1, "counted": False}
    # Someone who may not see it cannot count a view (and learns nothing).
    assert client_for(stranger).post(url, watched, format="json").status_code == 404
    # The next day counts again.
    ReelView.objects.update(day=timezone.now().date() - timedelta(days=1))
    later = client_for(viewer).post(url, watched, format="json").json()["data"]
    assert later == {"view_count": 2, "counted": True}
    data = client_for(viewer).get(reverse("reels:reel-detail", args=[reel_id])).json()["data"]
    assert data["reel"]["view_count"] == 2 and data["reel"]["viewed_today"] is True
