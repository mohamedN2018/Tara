"""WP 4.8: "Why am I seeing this?" v2, ``GET /api/v1/feed/why/{item_type}/{item_id}/``.

404, with one identical body, unless the item was served to this viewer (a serve
token issued to them for it, or their current Home ranking session) and is still
visible to them now. Factors are the viewer's own; a sensitive topic is masked.
"""

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from feed.models import Affinity, FeedItem, PostHide, RelationshipFlag

from intel import why
from intel.models import ItemType, Surface
from intel.ranking import serve_tokens

from . import world as w

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


def _row(viewer, author, reason="friend", *, post_id=None, author_type="user"):
    post_id = post_id or w.post(author, author_type=author_type)
    FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason=reason,
        snapshot={"post_id": post_id, "author_id": author, "author_type": author_type},
        post_created_at=timezone.now() - timedelta(minutes=5),
    )
    return post_id


def _token(viewer, post_id, *, source="friend", mode="recent", surface=Surface.HOME):
    return serve_tokens.issue(
        viewer, ItemType.POST, post_id, surface, source=source, reason=mode, position=0
    )


def _why(client, post_id, token=None, item_type="post"):
    url = reverse("intel:why", args=[item_type, post_id])
    return client.get(url, {"st": token} if token else {})


def _codes(resp):
    return [f["code"] for f in resp.json()["data"]["factors"]]


# ---- authorization ----------------------------------------------------------------


def test_a_served_item_explains_itself(client_for):
    viewer, friend = w.uid(), w.uid()
    post_id = _row(viewer, friend)
    resp = _why(client_for(viewer), post_id, _token(viewer, post_id))
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert body["item"] == f"post:{post_id}" and body["mode"] == "recent"
    assert body["surface"] == "home"
    assert body["factors"] == [{"code": "friend", "author_id": friend}]


def test_identical_404_for_missing_invisible_and_not_served(client_for):
    viewer, stranger, other = w.uid(), w.uid(), w.uid()
    client = client_for(viewer)
    private = w.post(stranger, audience="only_me")  # exists, never visible to viewer
    friend_post = _row(viewer, w.uid())  # visible, but never served
    other_token_post = _row(viewer, w.uid())
    bodies = [
        _why(client, str(uuid.uuid4())),  # no such item
        _why(client, private),  # private, no token
        _why(client, private, _token(viewer, private, source="follow_pull")),  # forged reach
        _why(client, friend_post),  # visible but not served
        _why(client, other_token_post, _token(other, other_token_post)),  # another viewer's token
        _why(client, friend_post, "garbage"),
        _why(client, friend_post, _token(viewer, private)),  # a token for a different item
        _why(client, "not-a-uuid"),
        _why(client, friend_post, item_type="group"),
    ]
    assert {r.status_code for r in bodies} == {404}
    # Identical apart from the per-request id.
    shapes = set()
    for r in bodies:
        error = r.json()["error"]
        error.pop("request_id")
        shapes.add(repr(error))
    assert shapes == {repr({"code": "not_found", "message": "Not found.", "details": []})}


def test_an_expired_token_is_refused(client_for):
    viewer = w.uid()
    post_id = _row(viewer, w.uid())
    old = serve_tokens.issue(
        viewer, ItemType.POST, post_id, Surface.HOME, now=timezone.now().timestamp() - 2 * 86400
    )
    assert _why(client_for(viewer), post_id, old).status_code == 404


def test_the_current_ranking_session_proves_serving(client_for):
    viewer, friend = w.uid(), w.uid()
    post_id = _row(viewer, friend)
    client = client_for(viewer)
    assert _why(client, post_id).status_code == 404
    page = client.get(reverse("feed:home-feed"), {"mode": "for_you"}).json()
    assert post_id in [i["post_id"] for i in page["data"]]
    resp = _why(client, post_id)  # no token: the session says it was served
    assert resp.status_code == 200
    assert resp.json()["data"]["mode"] == "for_you"
    assert resp.json()["data"]["cfg_version"] == "home@1"
    # Another viewer's session never proves anything for this one.
    assert _why(client_for(w.uid()), post_id).status_code == 404


def test_session_factors_are_the_stored_ranking_terms(client_for):
    viewer, author = w.uid(), w.uid()
    post_id = w.post(author, age=timedelta(days=10))  # old: freshness adds ~nothing
    FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason="follow",
        snapshot={"post_id": post_id, "author_id": author},
        post_created_at=timezone.now() - timedelta(days=10),
    )
    RelationshipFlag.objects.create(
        actor_id=viewer, target_id=author, kind="favorite", occurred_at=timezone.now()
    )
    Affinity.objects.create(account_id=viewer, author_id=author, interactions=5)
    client = client_for(viewer)
    client.get(reverse("feed:home-feed"), {"mode": "for_you"})
    resp = _why(client, post_id)
    assert resp.status_code == 200, resp.content
    assert _codes(resp) == ["follow", "favorite", "interacted_author"]


def test_served_then_gone_is_404(client_for):
    viewer, friend = w.uid(), w.uid()
    client = client_for(viewer)
    hidden = _row(viewer, friend)
    token = _token(viewer, hidden)
    PostHide.objects.create(
        account_id=viewer, post_id=hidden, author_id=friend, reason="not_interested"
    )
    assert _why(client, hidden, token).status_code == 404
    unfollowed = _row(viewer, w.uid(), "follow")
    token = _token(viewer, unfollowed, source="follow")
    FeedItem.objects.filter(post_id=unfollowed).delete()
    assert _why(client, unfollowed, token).status_code == 404
    blocked_author = w.uid()
    blocked = _row(viewer, blocked_author)
    token = _token(viewer, blocked)
    w.block(blocked_author, viewer)
    assert _why(client, blocked, token).status_code == 404


def test_a_pulled_group_post_needs_the_membership_now(client_for):
    viewer, author = w.uid(), w.uid()
    gid = w.group(privacy="private")
    w.member(viewer, gid)
    post_id = w.post(author, audience="group", group=gid)
    token = _token(viewer, post_id, source="groups", mode="for_you")
    client = client_for(viewer)
    resp = _why(client, post_id, token)
    assert resp.status_code == 200
    assert _codes(resp)[0] == "group_member"
    w.member(viewer, gid, state="banned")
    assert _why(client, post_id, token).status_code == 404


def test_a_pulled_post_feed_does_not_know_is_404(client_for):
    viewer, unknown = w.uid(), str(uuid.uuid4())
    token = _token(viewer, unknown, source="follow_pull", mode="for_you")
    assert _why(client_for(viewer), unknown, token).status_code == 404


def test_a_public_reel_from_the_pool(client_for):
    viewer, author = w.uid(), w.uid()
    reel = w.post(author, type="reel")
    token = serve_tokens.issue(
        viewer, ItemType.REEL, reel, Surface.REELS, source="reels", reason="for_you"
    )
    claims = {"sub": viewer, "is_minor": False, "age_band": "25-34"}
    body = why.explain(claims, "reel", reel, token)
    assert body["factors"][0] == {"code": "public_pool", "format": "reel"}
    # A limited (unknown-age) viewer is not shown unlisted discovery (E9).
    assert _why(client_for(viewer), reel, token, item_type="reel").status_code == 404


# ---- factors ----------------------------------------------------------------------


def test_for_you_lists_the_ranking_terms_that_applied(client_for):
    viewer, author = w.uid(), w.uid()
    post_id = _row(viewer, author, "follow")
    RelationshipFlag.objects.create(
        actor_id=viewer, target_id=author, kind="favorite", occurred_at=timezone.now()
    )
    Affinity.objects.create(account_id=viewer, author_id=author, interactions=5)
    PostHide.objects.create(account_id=viewer, post_id=w.uid(), author_id=author, reason="annoying")
    resp = _why(
        client_for(viewer), post_id, _token(viewer, post_id, source="follow", mode="for_you")
    )
    assert resp.status_code == 200
    assert _codes(resp) == ["follow", "favorite", "interacted_author"]  # capped at 3


def test_demoted_feedback_and_the_interaction_threshold(client_for):
    viewer, author = w.uid(), w.uid()
    post_id = _row(viewer, author, "follow")
    Affinity.objects.create(account_id=viewer, author_id=author, interactions=2)  # below 3
    PostHide.objects.create(
        account_id=viewer, post_id=w.uid(), author_id=author, reason="dislike_creator"
    )
    resp = _why(
        client_for(viewer), post_id, _token(viewer, post_id, source="follow", mode="for_you")
    )
    assert _codes(resp) == ["follow", "demoted_feedback"]


def test_chronological_modes_only_give_the_relationship(client_for):
    viewer, author = w.uid(), w.uid()
    post_id = _row(viewer, author, "follow")
    RelationshipFlag.objects.create(
        actor_id=viewer, target_id=author, kind="favorite", occurred_at=timezone.now()
    )
    for mode in ("recent", "following", "friends", "favorites"):
        token = _token(viewer, post_id, source="follow", mode=mode)
        resp = _why(client_for(viewer), post_id, token)
        assert _codes(resp) == ["follow"]
        assert resp.json()["data"]["mode"] == mode


def test_own_post_and_followed_page(client_for):
    viewer = w.uid()
    own = _row(viewer, viewer, "self")
    assert _codes(_why(client_for(viewer), own, _token(viewer, own, source="self"))) == ["self"]
    page = w.page(w.uid())
    page_post = _row(viewer, page, "follow", author_type="page")
    resp = _why(client_for(viewer), page_post, _token(viewer, page_post, source="follow"))
    assert resp.json()["data"]["factors"] == [{"code": "page_follow", "author_id": page}]


def test_no_private_data_of_others_in_the_body(client_for):
    viewer, author, someone = w.uid(), w.uid(), w.uid()
    post_id = _row(viewer, author)
    # Someone else's favorite, affinity and dislike of the same author.
    RelationshipFlag.objects.create(
        actor_id=someone, target_id=author, kind="favorite", occurred_at=timezone.now()
    )
    Affinity.objects.create(account_id=someone, author_id=author, interactions=50)
    resp = _why(client_for(viewer), post_id, _token(viewer, post_id, mode="for_you"))
    assert _codes(resp) == ["friend"]
    assert someone not in resp.content.decode()


def test_a_sensitive_topic_is_masked():
    assert why.topic_factor("technology", sensitive=False) == {
        "code": "rec_topic",
        "topic": "technology",
    }
    masked = why.topic_factor("religion", sensitive=True)
    assert masked == {"code": "rec_topic_sensitive"}
    assert "religion" not in str(masked)


def test_why_needs_authentication():
    from rest_framework.test import APIClient

    assert APIClient().get(reverse("intel:why", args=["post", w.uid()])).status_code == 401
