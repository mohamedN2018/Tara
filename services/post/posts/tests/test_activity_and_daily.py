"""Polish track: the settings activity log, the studio's engagement over time
and the content library's search and date filters."""

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from posts import services
from posts.models import BlockedPair, Comment, Post, PostReaction, SavedItem

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _activity(client, **params):
    return client.get(reverse("posts:activity-log"), params)


# ---- activity log ----------------------------------------------------------------------


def test_activity_log_lists_only_my_own_actions_newest_first(client_for):
    me, other = _acct(), _acct()
    mine = client_for(me)
    theirs = services.create_post(other, body="their post", audience="public")
    own = services.create_post(me, body="my post", audience="public")
    assert (
        mine.post(
            reverse("posts:post-reactions", args=[theirs.id]), {"type": "love"}, format="json"
        ).status_code
        == 200
    )
    assert (
        mine.post(
            reverse("posts:post-comments", args=[theirs.id]), {"body": "nice one"}, format="json"
        ).status_code
        == 201
    )
    assert mine.post(reverse("posts:post-save", args=[theirs.id])).status_code == 200
    # Someone else's actions never show in my log.
    stranger = client_for(other)
    stranger.post(reverse("posts:post-reactions", args=[own.id]), {"type": "like"}, format="json")
    stranger.post(reverse("posts:post-comments", args=[own.id]), {"body": "hey"}, format="json")

    resp = _activity(mine)
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert [r["kind"] for r in rows] == ["save", "comment", "reaction", "post"]
    save, comment, reaction, post = rows
    assert reaction["reaction"] == "love"
    assert reaction["target"]["post_id"] == str(theirs.id)
    assert reaction["target"]["excerpt"] == "their post"
    assert comment["text"] == "nice one"
    assert save["item_type"] == "post" and save["item_id"] == str(theirs.id)
    assert post["text"] == "my post" and post["target"]["post_id"] == str(own.id)
    assert resp.json()["page"]["has_more"] is False


def test_activity_log_filters_by_kind_and_rejects_unknown(client_for):
    me = _acct()
    mine = client_for(me)
    post = services.create_post(me, body="p", audience="public")
    mine.post(reverse("posts:post-comments", args=[post.id]), {"body": "c"}, format="json")
    rows = _activity(mine, kind="comment").json()["data"]
    assert [r["kind"] for r in rows] == ["comment"]
    assert _activity(mine, kind="secrets").status_code == 400
    assert _activity(mine, cursor="not-a-cursor").status_code == 400


def test_activity_log_pages_through_everything_once(client_for):
    me = _acct()
    mine = client_for(me)
    target = services.create_post(_acct(), body="t", audience="public")
    for i in range(4):
        services.create_post(me, body=f"post {i}", audience="public")
    mine.post(reverse("posts:post-reactions", args=[target.id]), {"type": "like"}, format="json")
    for i in range(3):
        mine.post(
            reverse("posts:post-comments", args=[target.id]), {"body": f"c{i}"}, format="json"
        )
    # Make some rows share a timestamp across kinds: the cursor must not skip or repeat.
    same = timezone.now() - timedelta(hours=1)
    Post.objects.filter(author_id=me).update(created_at=same)
    Comment.objects.filter(author_id=me).update(created_at=same)

    seen, cursor = [], None
    for _ in range(10):
        params = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = _activity(mine, **params).json()
        seen += [(r["kind"], r["id"]) for r in body["data"]]
        cursor = body["page"]["next_cursor"]
        if not body["page"]["has_more"]:
            break
    assert len(seen) == 8 and len(set(seen)) == 8


def test_activity_log_hides_the_target_once_i_cannot_see_it(client_for):
    me, author = _acct(), _acct()
    mine = client_for(me)
    blocked_post = services.create_post(author, body="secret words", audience="public")
    deleted_post = services.create_post(author, body="gone soon", audience="public")
    for p in (blocked_post, deleted_post):
        mine.post(reverse("posts:post-reactions", args=[p.id]), {"type": "like"}, format="json")
    BlockedPair.objects.create(blocker_id=author, blocked_id=me)
    Post.objects.filter(id=deleted_post.id).update(deleted_at=timezone.now())

    rows = _activity(mine, kind="reaction").json()["data"]
    assert len(rows) == 2
    assert all(r["target"] is None for r in rows)
    assert "secret words" not in str(rows) and "gone soon" not in str(rows)


def test_activity_log_needs_a_signed_in_account(client):
    assert client.get(reverse("posts:activity-log")).status_code in (401, 403)


# ---- engagement over time ---------------------------------------------------------------


def _daily(client, **params):
    return client.get(reverse("posts:studio-daily"), params)


def test_daily_counts_engagement_from_others_per_local_day(client_for):
    me, fan = _acct(), _acct()
    mine = client_for(me)
    post = services.create_post(me, body="mine", audience="public")
    other_post = services.create_post(fan, body="not mine", audience="public")
    fans = client_for(fan)
    fans.post(reverse("posts:post-reactions", args=[post.id]), {"type": "like"}, format="json")
    fans.post(reverse("posts:post-comments", args=[post.id]), {"body": "wow"}, format="json")
    fans.post(reverse("posts:post-save", args=[post.id]))
    # My own reaction and comment are not engagement; nor is anything on others' posts.
    mine.post(reverse("posts:post-reactions", args=[post.id]), {"type": "love"}, format="json")
    mine.post(reverse("posts:post-comments", args=[post.id]), {"body": "me"}, format="json")
    mine.post(
        reverse("posts:post-reactions", args=[other_post.id]), {"type": "love"}, format="json"
    )

    today = timezone.now().date()
    start = today - timedelta(days=6)
    resp = _daily(mine, **{"from": start.isoformat(), "to": today.isoformat(), "tz": "UTC"})
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert len(data["days"]) == 7
    assert data["days"][0]["date"] == start.isoformat()
    assert data["totals"] == {
        "views": 0,
        "reactions": 1,
        "comments": 1,
        "shares": 0,
        "saves": 1,
        "posts": 1,
    }
    assert data["days"][-1]["reactions"] == 1


def test_daily_uses_the_viewers_time_zone(client_for):
    me, fan = _acct(), _acct()
    post = services.create_post(me, body="mine", audience="public")
    client_for(fan).post(
        reverse("posts:post-reactions", args=[post.id]), {"type": "like"}, format="json"
    )
    # 23:30 UTC on a day is already the next day in Cairo (UTC+2 or +3).
    late = timezone.now().replace(hour=23, minute=30, second=0, microsecond=0) - timedelta(days=2)
    PostReaction.objects.filter(post=post).update(created_at=late)
    day = late.date()
    params = {"from": day.isoformat(), "to": (day + timedelta(days=1)).isoformat()}
    utc = _daily(client_for(me), **params, tz="UTC").json()["data"]["days"]
    cairo = _daily(client_for(me), **params, tz="Africa/Cairo").json()["data"]["days"]
    assert [d["reactions"] for d in utc] == [1, 0]
    assert [d["reactions"] for d in cairo] == [0, 1]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"from": "2026-01-02", "to": "2026-01-01"},
        {"from": "2025-01-01", "to": "2026-06-01"},
        {"from": "yesterday", "to": "2026-01-01"},
        {"from": "2026-01-01", "to": "2026-01-02", "tz": "Mars/Olympus"},
    ],
)
def test_daily_rejects_bad_ranges(client_for, params):
    assert _daily(client_for(_acct()), **params).status_code == 400


# ---- content library search and dates ---------------------------------------------------


def test_library_search_and_date_range(client_for):
    me = _acct()
    mine = client_for(me)
    a = services.create_post(me, body="Cairo sunset photos", audience="public")
    b = services.create_post(me, body="Morning coffee", audience="public")
    old = services.create_post(me, body="An old sunset", audience="public")
    Post.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=40))
    services.create_post(_acct(), body="someone else's sunset", audience="public")

    url = reverse("posts:studio-published")
    found = mine.get(url, {"q": "SUNSET"}).json()["data"]
    assert {p["id"] for p in found} == {str(a.id), str(old.id)}
    since = (timezone.now() - timedelta(days=7)).isoformat()
    recent = mine.get(url, {"from": since}).json()["data"]
    assert {p["id"] for p in recent} == {str(a.id), str(b.id)}
    both = mine.get(url, {"q": "sunset", "from": since}).json()["data"]
    assert [p["id"] for p in both] == [str(a.id)]
    assert mine.get(url, {"q": "x" * 101}).status_code == 400
    assert mine.get(url, {"from": "2026-01-01"}).status_code == 400  # no offset


def test_saved_activity_row_for_a_listing_has_no_post_target(client_for):
    me = _acct()
    listing = str(uuid.uuid4())
    client_for(me).post(
        reverse("posts:saved-list"), {"item_type": "listing", "item_id": listing}, format="json"
    )
    assert SavedItem.objects.filter(owner_id=me).count() == 1
    rows = _activity(client_for(me), kind="save").json()["data"]
    assert rows[0]["item_type"] == "listing" and rows[0]["item_id"] == listing
    assert rows[0]["target"] is None
