"""Milestone 1.4: per-type reaction counts, who reacted, who shared, post.unreacted."""

import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from posts import services
from posts.clients import Relationship
from posts.models import BlockedPair, OutboxEvent, Post, PostReactionCount

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _counts(post) -> dict:
    return dict(
        PostReactionCount.objects.filter(post=post, count__gt=0).values_list("type", "count")
    )


def test_per_type_counts_follow_add_change_and_remove(client_for):
    author, a, b, c = _acct(), _acct(), _acct(), _acct()
    post = services.create_post(author, body="p")
    services.react(a, str(post.id), "like")
    services.react(b, str(post.id), "love")
    services.react(c, str(post.id), "love")
    assert _counts(post) == {"like": 1, "love": 2}

    services.react(a, str(post.id), "love")  # change
    assert _counts(post) == {"love": 3}
    services.react(a, str(post.id), "love")  # same again: nothing changes
    assert _counts(post) == {"love": 3}

    services.unreact(b, str(post.id))
    services.unreact(b, str(post.id))  # twice: no double decrement
    assert _counts(post) == {"love": 2}
    assert Post.objects.get(id=post.id).reaction_count == 2

    data = client_for(author).get(reverse("posts:post-detail", args=[post.id])).json()["data"]
    assert data["reaction_counts"] == {"love": 2}
    assert data["reaction_count"] == 2


def test_unreact_emits_post_unreacted_once():
    author, reactor = _acct(), _acct()
    post = services.create_post(author, body="p")
    services.react(reactor, str(post.id), "wow")
    services.unreact(reactor, str(post.id))
    services.unreact(reactor, str(post.id))
    events = OutboxEvent.objects.filter(event_type="post.unreacted")
    assert events.count() == 1
    assert events.get().payload["payload"] == {
        "post_id": str(post.id),
        "reactor": reactor,
        "reaction_type": "wow",
        "author_id": author,
    }


def test_who_reacted_filters_by_type_and_pages(client_for):
    author = _acct()
    post = services.create_post(author, body="p")
    lovers = [_acct() for _ in range(3)]
    for account in lovers:
        services.react(account, str(post.id), "love")
    liker = _acct()
    services.react(liker, str(post.id), "like")
    client = client_for(author)
    url = reverse("posts:post-reactions", args=[post.id])

    everyone = client.get(url).json()["data"]
    assert {r["account_id"] for r in everyone} == {*lovers, liker}

    seen, cursor = [], None
    for _ in range(5):
        body = client.get(
            url, {"type": "love", "limit": 2, **({"cursor": cursor} if cursor else {})}
        ).json()
        seen += body["data"]
        cursor = body["page"]["next_cursor"]
        if not cursor:
            break
    assert sorted(r["account_id"] for r in seen) == sorted(lovers)
    assert {r["type"] for r in seen} == {"love"}

    assert client.get(url, {"type": "meh"}).status_code == 400


def test_who_reacted_is_404_when_the_post_is_hidden(client_for, monkeypatch):
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    author = _acct()
    post = services.create_post(author, body="p", audience="friends")
    services.react(author, str(post.id), "like")
    resp = client_for(_acct()).get(reverse("posts:post-reactions", args=[post.id]))
    assert resp.status_code == 404


def test_who_reacted_leaves_out_blocked_accounts_both_ways(client_for):
    viewer, author, blocked, blocker, ok = _acct(), _acct(), _acct(), _acct(), _acct()
    post = services.create_post(author, body="p")
    for account in (blocked, blocker, ok):
        services.react(account, str(post.id), "like")
    BlockedPair.objects.create(blocker_id=viewer, blocked_id=blocked)
    BlockedPair.objects.create(blocker_id=blocker, blocked_id=viewer)
    resp = client_for(viewer).get(reverse("posts:post-reactions", args=[post.id]))
    assert [r["account_id"] for r in resp.json()["data"]] == [ok]


def test_who_shared_lists_only_shares_the_viewer_can_open(client_for, monkeypatch):
    author, public_sharer, friends_sharer, blocked_sharer, viewer = (_acct() for _ in range(5))
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    original = services.create_post(author, body="root")
    public_share = services.share(public_sharer, str(original.id), body="look")
    services.share(friends_sharer, str(original.id), audience="friends")
    services.share(blocked_sharer, str(original.id))
    deleted = services.share(_acct(), str(original.id))
    services.delete_post(deleted.author_id, str(deleted.id))
    BlockedPair.objects.create(blocker_id=blocked_sharer, blocked_id=viewer)

    resp = client_for(viewer).get(reverse("posts:post-shares", args=[original.id]))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [s["account_id"] for s in data] == [public_sharer]
    assert data[0]["share_post_id"] == str(public_share.id)
    assert data[0]["body"] == "look"


def test_who_shared_is_404_when_the_original_is_hidden(client_for, monkeypatch):
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    original = services.create_post(_acct(), body="p", audience="friends")
    resp = client_for(_acct()).get(reverse("posts:post-shares", args=[original.id]))
    assert resp.status_code == 404


def test_reaction_counts_do_not_add_queries_per_post(client_for):
    viewer = _acct()
    client = client_for(viewer)

    def reacted_post():
        post = services.create_post(_acct(), body="p")
        services.react(_acct(), str(post.id), "love")
        services.react(_acct(), str(post.id), "like")
        return post

    def batch(posts):
        with CaptureQueriesContext(connection) as ctx:
            resp = client.post(
                reverse("posts:post-batch"), {"ids": [str(p.id) for p in posts]}, format="json"
            )
        assert resp.status_code == 200
        assert all(p["reaction_counts"] for p in resp.json()["data"])
        return len(ctx)

    posts = [reacted_post()]
    few = batch(posts)
    posts += [reacted_post() for _ in range(5)]
    assert batch(posts) == few
