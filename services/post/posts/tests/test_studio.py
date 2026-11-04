"""Track T8: creator studio reads (summary, content library, planner calendar)."""

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from posts.models import Post, SavedCollection, SavedItem

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _create(client, **data) -> dict:
    resp = client.post(reverse("posts:post-create"), {"body": "hi", **data}, format="json")
    assert resp.status_code == 201, resp.content
    return resp.json()["data"]


def _iso(dt) -> str:
    return dt.isoformat()


def _calendar(client, start, end):
    return client.get(reverse("posts:calendar"), {"from": _iso(start), "to": _iso(end)})


# ---- summary ---------------------------------------------------------------------------


def test_summary_counts_only_my_live_published_posts(client_for):
    me, other = _acct(), _acct()
    mine = client_for(me)
    a = _create(mine, body="one")
    b = _create(mine, body="two")
    gone = _create(mine, body="deleted")
    removed = _create(mine, body="removed")
    _create(mine, body="a draft", draft=True)
    _create(mine, body="later", publish_at=_iso(timezone.now() + timedelta(days=2)))
    _create(client_for(other), body="not mine")
    Post.objects.filter(id=a["id"]).update(reaction_count=5, comment_count=2, share_count=1)
    Post.objects.filter(id=b["id"]).update(reaction_count=1)
    Post.objects.filter(id=gone["id"]).update(deleted_at=timezone.now(), reaction_count=50)
    Post.objects.filter(id=removed["id"]).update(
        moderation_status=Post.ModerationStatus.REMOVED, reaction_count=70
    )
    collection = SavedCollection.objects.create(owner_id=other)
    SavedItem.objects.create(
        owner_id=other, collection=collection, item_type="post", item_id=a["id"]
    )

    resp = mine.get(reverse("posts:studio-summary"))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert {k: data[k] for k in ("posts", "reactions", "comments", "shares", "saves")} == {
        "posts": 2,
        "reactions": 6,
        "comments": 2,
        "shares": 1,
        "saves": 1,
    }
    assert data["drafts"] == 1
    assert data["scheduled"] == 1
    assert [p["id"] for p in data["top_posts"]] == [a["id"], b["id"]]
    # No invented metric: impressions and reach are not reported at all.
    assert "impressions" not in data and "reach" not in data


def test_summary_of_a_new_account_is_all_zero(client_for):
    data = client_for(_acct()).get(reverse("posts:studio-summary")).json()["data"]
    assert data["posts"] == data["reactions"] == data["saves"] == 0
    assert data["top_posts"] == []


def test_studio_needs_a_signed_in_account(client):
    assert client.get(reverse("posts:studio-summary")).status_code == 401
    assert client.get(reverse("posts:studio-published")).status_code == 401
    now = timezone.now()
    assert _calendar(client, now, now + timedelta(days=1)).status_code == 401


# ---- content library ---------------------------------------------------------------------


def test_published_lists_my_posts_newest_first_and_never_drafts(client_for):
    me, other = _acct(), _acct()
    mine = client_for(me)
    first = _create(mine, body="first")
    second = _create(mine, body="second")
    _create(mine, body="draft", draft=True)
    _create(client_for(other), body="other's")
    resp = mine.get(reverse("posts:studio-published"))
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()["data"]] == [second["id"], first["id"]]


def test_published_filters_by_type_and_rejects_unknown_types(client_for):
    mine = client_for(_acct())
    _create(mine, body="text")
    poll = _create(mine, body="question?", poll={"options": ["a", "b"]})
    resp = mine.get(reverse("posts:studio-published"), {"type": "poll"})
    assert [p["id"] for p in resp.json()["data"]] == [poll["id"]]
    assert mine.get(reverse("posts:studio-published"), {"type": "nope"}).status_code == 400


# ---- planner calendar -----------------------------------------------------------------------


def test_calendar_returns_only_my_scheduled_and_published_posts_in_range(client_for):
    me, other = _acct(), _acct()
    mine = client_for(me)
    now = timezone.now()
    published = _create(mine, body="out now")
    soon = _create(mine, body="soon", publish_at=_iso(now + timedelta(days=3)))
    far = _create(mine, body="far", publish_at=_iso(now + timedelta(days=40)))
    _create(mine, body="a draft", draft=True)
    deleted = _create(mine, body="deleted", publish_at=_iso(now + timedelta(days=2)))
    Post.objects.filter(id=deleted["id"]).update(deleted_at=now)
    _create(client_for(other), body="other's", publish_at=_iso(now + timedelta(days=3)))

    resp = _calendar(mine, now - timedelta(days=1), now + timedelta(days=10))
    assert resp.status_code == 200
    body = resp.json()
    assert [p["id"] for p in body["data"]] == [published["id"], soon["id"]]
    assert [p["state"] for p in body["data"]] == ["published", "scheduled"]
    assert body["meta"]["truncated"] is False
    later = _calendar(mine, now + timedelta(days=30), now + timedelta(days=42)).json()["data"]
    assert [p["id"] for p in later] == [far["id"]]


def test_calendar_validates_its_range(client_for):
    mine = client_for(_acct())
    now = timezone.now()
    assert _calendar(mine, now, now - timedelta(hours=1)).status_code == 400
    too_long = _calendar(mine, now, now + timedelta(days=60))
    assert too_long.status_code == 400
    assert too_long.json()["error"]["code"] == "range_too_long"
    assert mine.get(reverse("posts:calendar")).status_code == 400
    naive = mine.get(
        reverse("posts:calendar"), {"from": "2026-11-01T00:00:00", "to": "2026-11-30T00:00:00"}
    )
    assert naive.status_code == 400
    garbage = mine.get(reverse("posts:calendar"), {"from": "soon", "to": "later"})
    assert garbage.status_code == 400


def test_rescheduling_from_the_planner_moves_the_post_and_refuses_the_past(client_for):
    me = _acct()
    mine = client_for(me)
    now = timezone.now()
    post = _create(mine, body="move me", publish_at=_iso(now + timedelta(days=3)))
    url = reverse("posts:draft-detail", args=[post["id"]])
    target = now + timedelta(days=9)
    moved = mine.patch(url, {"publish_at": _iso(target)}, format="json")
    assert moved.status_code == 200
    assert moved.json()["data"]["state"] == "scheduled"
    day9 = _calendar(mine, target - timedelta(hours=1), target + timedelta(hours=1)).json()["data"]
    assert [p["id"] for p in day9] == [post["id"]]

    past = mine.patch(url, {"publish_at": _iso(now - timedelta(hours=1))}, format="json")
    assert past.status_code == 400
    assert past.json()["error"]["code"] == "publish_at_past"
    # Someone else cannot move it: 404, as for any draft that is not theirs.
    other = client_for(_acct()).patch(url, {"publish_at": _iso(target)}, format="json")
    assert other.status_code == 404


# ---- engagement (comments on my posts) ---------------------------------------------------


def test_studio_comments_lists_others_comments_on_my_live_posts_newest_first(client_for):
    from posts import services
    from posts.models import BlockedPair, Comment

    me, fan, blocked, stranger = _acct(), _acct(), _acct(), _acct()
    mine = services.create_post(me, body="my post body")
    gone = services.create_post(me, body="deleted later")
    theirs = services.create_post(stranger, body="not mine")
    first = services.add_comment(fan, str(mine.id), "first")
    second = services.add_comment(fan, str(mine.id), "second")
    services.add_comment(me, str(mine.id), "my own reply")
    removed = services.add_comment(fan, str(mine.id), "removed")
    Comment.objects.filter(id=removed.id).update(moderation_status=Comment.ModerationStatus.REMOVED)
    services.add_comment(blocked, str(mine.id), "from a blocked account")
    BlockedPair.objects.create(blocker_id=me, blocked_id=blocked)
    services.add_comment(fan, str(gone.id), "on a deleted post")
    Post.objects.filter(id=gone.id).update(deleted_at=timezone.now())
    services.add_comment(fan, str(theirs.id), "on someone else's post")

    resp = client_for(me).get(reverse("posts:studio-comments"))
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert [r["id"] for r in rows] == [str(second.id), str(first.id)]
    assert rows[0]["post_id"] == str(mine.id)
    assert rows[0]["post_excerpt"] == "my post body"
    assert rows[0]["author_id"] == fan


def test_studio_comments_needs_sign_in(client):
    assert client.get(reverse("posts:studio-comments")).status_code == 401


# ---- insights (per post type) -------------------------------------------------------------


def test_studio_insights_groups_my_published_posts_by_type(client_for):
    me, other = _acct(), _acct()
    mine = client_for(me)
    a = _create(mine, body="one")
    b = _create(mine, body="two")
    _create(mine, body="a draft", draft=True)
    gone = _create(mine, body="deleted")
    _create(client_for(other), body="not mine")
    Post.objects.filter(id=a["id"]).update(reaction_count=3, comment_count=1)
    Post.objects.filter(id=b["id"]).update(share_count=2)
    Post.objects.filter(id=gone["id"]).update(deleted_at=timezone.now(), reaction_count=40)

    resp = mine.get(reverse("posts:studio-insights"))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["by_type"] == [
        {"type": "text", "posts": 2, "reactions": 3, "comments": 1, "shares": 2}
    ]
    assert [p["id"] for p in data["top_posts"]] == [a["id"], b["id"]]


def test_studio_insights_needs_sign_in(client):
    assert client.get(reverse("posts:studio-insights")).status_code == 401
