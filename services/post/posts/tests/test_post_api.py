"""Post API: creation/events, audience visibility, interactions, saves, reports."""

import uuid

import pytest
from django.urls import reverse

from posts import services
from posts.clients import Relationship
from posts.models import BlockedPair, OutboxEvent, Post, PostReaction, SavedItem

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _friends(value=True):
    return lambda a, b: Relationship(are_friends=value)


# ---- creation ---------------------------------------------------------------


def test_create_post_emits_event_and_extracts_tags(client_for):
    author = _acct()
    resp = client_for(author).post(
        reverse("posts:post-create"),
        {"body": "hello #tara @nadia world #Tara", "audience": "public"},
        format="json",
    )
    assert resp.status_code == 201
    post_id = resp.json()["data"]["id"]
    post = Post.objects.get(id=post_id)
    assert {h.hashtag.tag for h in post.hashtags.all()} == {"tara"}  # deduped, lowercased
    assert {m.mentioned_handle for m in post.mentions.all()} == {"nadia"}
    assert OutboxEvent.objects.filter(event_type="post.created").exists()


def test_empty_post_rejected(client_for):
    resp = client_for(_acct()).post(reverse("posts:post-create"), {"body": ""}, format="json")
    assert resp.status_code == 400


# ---- audience visibility ----------------------------------------------------


def test_public_post_visible_to_others(client_for, monkeypatch):
    author = _acct()
    post = services.create_post(author, body="public hi", audience="public")
    monkeypatch.setattr("posts.services.get_relationship", _friends(False))
    resp = client_for(_acct()).get(reverse("posts:post-detail", args=[post.id]))
    assert resp.status_code == 200


def test_friends_post_hidden_then_visible(client_for, monkeypatch):
    author = _acct()
    post = services.create_post(author, body="friends only", audience="friends")
    viewer = _acct()

    monkeypatch.setattr("posts.services.get_relationship", _friends(False))
    assert client_for(viewer).get(reverse("posts:post-detail", args=[post.id])).status_code == 404

    monkeypatch.setattr("posts.services.get_relationship", _friends(True))
    assert client_for(viewer).get(reverse("posts:post-detail", args=[post.id])).status_code == 200


def test_only_me_hidden_from_others(client_for, monkeypatch):
    author = _acct()
    post = services.create_post(author, body="secret", audience="only_me")
    monkeypatch.setattr("posts.services.get_relationship", _friends(True))
    assert client_for(_acct()).get(reverse("posts:post-detail", args=[post.id])).status_code == 404
    # Author still sees it.
    assert client_for(author).get(reverse("posts:post-detail", args=[post.id])).status_code == 200


def test_blocked_viewer_cannot_see_public_post(client_for):
    author = _acct()
    viewer = _acct()
    post = services.create_post(author, body="hi", audience="public")
    BlockedPair.objects.create(blocker_id=author, blocked_id=viewer)
    assert client_for(viewer).get(reverse("posts:post-detail", args=[post.id])).status_code == 404


# ---- interactions -----------------------------------------------------------


def test_react_is_idempotent_and_counts(client_for):
    author = _acct()
    post = services.create_post(author, body="hi", audience="public")
    client = client_for(author)
    url = reverse("posts:post-reactions", args=[post.id])
    assert client.post(url, {"type": "like"}, format="json").status_code == 200
    assert client.post(url, {"type": "love"}, format="json").status_code == 200  # change type
    assert PostReaction.objects.filter(post=post).count() == 1
    post.refresh_from_db()
    assert post.reaction_count == 1
    assert OutboxEvent.objects.filter(event_type="post.reacted").exists()


def test_comment_and_reply_events(client_for):
    author = _acct()
    post = services.create_post(author, body="hi", audience="public")
    client = client_for(author)
    c = client.post(
        reverse("posts:post-comments", args=[post.id]), {"body": "nice @x"}, format="json"
    )
    assert c.status_code == 201
    comment_id = c.json()["data"]["id"]
    r = client.post(
        reverse("posts:comment-replies", args=[comment_id]), {"body": "thanks"}, format="json"
    )
    assert r.status_code == 201
    post.refresh_from_db()
    assert post.comment_count == 2
    assert OutboxEvent.objects.filter(event_type="post.commented").exists()
    assert OutboxEvent.objects.filter(event_type="comment.replied").exists()


def test_save_unsave_idempotent(client_for):
    author = _acct()
    post = services.create_post(author, body="hi", audience="public")
    client = client_for(author)
    assert client.post(reverse("posts:post-save", args=[post.id])).status_code == 200
    assert client.post(reverse("posts:post-save", args=[post.id])).status_code == 200  # idempotent
    assert SavedItem.objects.filter(owner_id=author, item_type="post", item_id=post.id).count() == 1
    listing = client.get(reverse("posts:saved-list"))
    assert len(listing.json()["data"]) == 1
    assert client.delete(reverse("posts:post-save", args=[post.id])).status_code == 204


def test_report_emits_event(client_for):
    author = _acct()
    post = services.create_post(author, body="hi", audience="public")
    resp = client_for(_acct()).post(
        reverse("posts:post-report", args=[post.id]), {"reason": "spam"}, format="json"
    )
    assert resp.status_code == 202
    assert OutboxEvent.objects.filter(event_type="post.reported").exists()


# ---- author timeline (GET /posts/?author_id=) -------------------------------


def test_list_author_posts_requires_author_id(client_for):
    assert client_for(_acct()).get(reverse("posts:post-create")).status_code == 400


def test_list_author_posts_honours_audience(client_for, monkeypatch):
    author = _acct()
    services.create_post(author, body="p1 public", audience="public")
    services.create_post(author, body="p2 friends", audience="friends")

    # A non-friend sees only the public post.
    monkeypatch.setattr("posts.services.get_relationship", _friends(False))
    resp = client_for(_acct()).get(reverse("posts:post-create"), {"author_id": author})
    assert resp.status_code == 200
    assert [p["body"] for p in resp.json()["data"]] == ["p1 public"]

    # A friend sees both, newest first.
    monkeypatch.setattr("posts.services.get_relationship", _friends(True))
    resp = client_for(_acct()).get(reverse("posts:post-create"), {"author_id": author})
    assert [p["body"] for p in resp.json()["data"]] == ["p2 friends", "p1 public"]


# ---- batch + viewer state ----------------------------------------------------


def test_timeline_is_cursor_paginated(client_for):
    author = _acct()
    for i in range(3):
        services.create_post(author, body=f"p{i}", audience="public")
    client = client_for(_acct())

    first = client.get(reverse("posts:post-create"), {"author_id": author, "limit": 2}).json()
    assert [p["body"] for p in first["data"]] == ["p2", "p1"]
    assert first["page"]["has_more"] is True

    params = {"author_id": author, "limit": 2, "cursor": first["page"]["next_cursor"]}
    second = client.get(reverse("posts:post-create"), params).json()
    assert [p["body"] for p in second["data"]] == ["p0"]


def test_batch_keeps_order_and_viewer_state_and_drops_invisible(client_for):
    author, viewer = _acct(), _acct()
    one = services.create_post(author, body="one", audience="public")
    two = services.create_post(author, body="two", audience="public")
    private = services.create_post(author, body="private", audience="only_me")
    gone = services.create_post(author, body="gone", audience="public")
    services.delete_post(author, str(gone.id))
    services.react(viewer, str(two.id), "like")
    services.save_item(viewer, "post", str(two.id))

    resp = client_for(viewer).post(
        reverse("posts:post-batch"),
        {"ids": [str(two.id), str(private.id), str(gone.id), str(one.id)]},
        format="json",
    )

    data = resp.json()["data"]
    assert [p["body"] for p in data] == ["two", "one"]
    assert (data[0]["my_reaction"], data[0]["is_saved"]) == ("like", True)
    assert (data[1]["my_reaction"], data[1]["is_saved"]) == (None, False)


def test_timeline_checks_each_author_with_graph_only_once(client_for, monkeypatch):
    author = _acct()
    services.create_post(author, body="a", audience="friends")
    services.create_post(author, body="b", audience="friends")
    calls = []

    def relationship(a, b):
        calls.append(b)
        return Relationship(are_friends=True)

    monkeypatch.setattr("posts.services.get_relationship", relationship)
    client_for(_acct()).get(reverse("posts:post-create"), {"author_id": author})
    assert len(calls) == 1
