"""Full video pages (4b.9): the audience rule runs in SQL and a bounded
over-fetch fills the page, so a page returns 20 when 20 visible exist."""

import pytest
from django.urls import reverse
from posts import services
from posts.models import BlockedPair, Post

from .conftest import acct
from .seeding import make_video

pytestmark = pytest.mark.django_db


def _videos(client, **params):
    resp = client.get(reverse("posts:post-create"), {"type": "video", **params})
    assert resp.status_code == 200, resp.content
    body = resp.json()
    return [p["id"] for p in body["data"]], body["page"]


def test_a_page_is_full_when_twenty_visible_exist_among_hidden_ones(client_for, graph):
    me, stranger, friend = acct(), acct(), acct()
    graph.befriend(me, friend)
    visible, minute = [], 0
    for i in range(30):
        minute += 1
        make_video(stranger, minutes_ago=minute, audience="friends")  # not a friend: hidden
        minute += 1
        author, audience = (friend, "friends") if i % 2 else (stranger, "public")
        visible.append(make_video(author, minutes_ago=minute, audience=audience))
    ids, page = _videos(client_for(me))
    assert ids == visible[:20] and page["has_more"] is True
    rest, page = _videos(client_for(me), cursor=page["next_cursor"])
    assert rest == visible[20:] and page["has_more"] is False and page["next_cursor"] is None


def test_python_only_checks_are_bounded_and_skip_nothing(client_for, monkeypatch):
    """Rows SQL lets through but the per-item check drops are read at most
    ``VIDEO_MAX_FETCHES`` x ``VIDEO_OVERFETCH`` x the page size at a time."""
    me, author = acct(), acct()
    dropped = {make_video(author, minutes_ago=m) for m in range(1, 41)}
    later = [make_video(acct(), minutes_ago=m) for m in range(41, 71)]
    monkeypatch.setattr(
        services,
        "visible_to_viewer",
        lambda viewer, post, cache=None, blocked=None: str(post.id) not in dropped,
    )
    ids, page = _videos(client_for(me), limit=10)  # 3 x 20 candidates: 40 dropped, 10 kept
    assert ids == later[:10] and page["has_more"] is True
    ids, page = _videos(client_for(me), limit=5)  # 3 x 10 candidates: all dropped
    assert ids == [] and page["has_more"] is True  # short, never an unbounded scan
    seen, cursor = [], page["next_cursor"]
    while cursor:
        ids, page = _videos(client_for(me), limit=5, cursor=cursor)
        seen.extend(ids)
        cursor = page["next_cursor"]
    assert seen == later  # nothing skipped, nothing repeated


def test_video_visibility_rules_still_hold(client_for, graph):
    me, friend, followed, stranger, blocked = acct(), acct(), acct(), acct(), acct()
    graph.befriend(me, friend)
    graph.follow(me, followed)
    mine = make_video(me, minutes_ago=1, audience="only_me")
    friends_only = make_video(friend, minutes_ago=2, audience="friends")
    followers_only = make_video(followed, minutes_ago=3, audience="followers")
    make_video(stranger, minutes_ago=4, audience="followers")
    make_video(stranger, minutes_ago=5, audience="friends")
    make_video(friend, minutes_ago=6, audience="only_me")
    make_video(blocked, minutes_ago=7)
    BlockedPair.objects.create(blocker_id=blocked, blocked_id=me)
    removed = make_video(stranger, minutes_ago=8)
    Post.objects.filter(pk=removed).update(moderation_status=Post.ModerationStatus.REMOVED)
    deleted = make_video(stranger, minutes_ago=9)
    Post.objects.filter(pk=deleted).update(deleted_at=Post.objects.get(pk=deleted).created_at)
    public = make_video(stranger, minutes_ago=10)
    assert _videos(client_for(me))[0] == [mine, friends_only, followers_only, public]
    # One author's videos (a profile's Videos tab).
    assert _videos(client_for(me), author_id=followed)[0] == [followers_only]
    assert _videos(client_for(stranger), author_id=friend)[0] == []
    assert _videos(client_for(blocked), author_id=me)[0] == []


def test_graph_down_leaves_public_and_own_videos_only(client_for, graph):
    me, friend = acct(), acct()
    graph.befriend(me, friend)
    public = make_video(friend, minutes_ago=1)
    make_video(friend, minutes_ago=2, audience="friends")
    mine = make_video(me, minutes_ago=3, audience="friends")
    graph.down = True
    assert _videos(client_for(me))[0] == [public, mine]


def test_a_bad_cursor_or_author_is_a_bad_request(client_for):
    me = client_for(acct())
    url = reverse("posts:post-create")
    assert me.get(url, {"type": "video", "cursor": "%%%"}).status_code == 400
    assert me.get(url, {"type": "video", "author_id": "nope"}).status_code == 400
