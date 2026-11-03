"""Comments and saved lists: paging, blocks, reply events, query counts, event purge."""

import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from posts import services
from posts.models import BlockedPair, OutboxEvent, Post, ProcessedEvent
from tara_events.tasks import purge_events

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _walk(client, url):
    """Every page of a list endpoint, following next_cursor."""
    items, cursor = [], None
    for _ in range(20):
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        resp = client.get(url, params)
        assert resp.status_code == 200
        body = resp.json()
        items += body["data"]
        cursor = body["page"]["next_cursor"]
        if not cursor:
            return items
    raise AssertionError("pagination did not end")


def test_comments_are_paged_oldest_first(client_for):
    author = _acct()
    post = services.create_post(author, body="p")
    ids = [str(services.add_comment(author, str(post.id), f"c{i}").id) for i in range(5)]
    got = _walk(client_for(author), reverse("posts:post-comments", args=[post.id]))
    assert [c["id"] for c in got] == ids


def test_comments_hide_blocked_authors_both_ways(client_for):
    viewer, author, blocked, blocker = _acct(), _acct(), _acct(), _acct()
    post = services.create_post(author, body="p")
    visible = services.add_comment(author, str(post.id), "ok")
    services.add_comment(blocked, str(post.id), "hidden")
    services.add_comment(blocker, str(post.id), "hidden too")
    BlockedPair.objects.create(blocker_id=viewer, blocked_id=blocked)
    BlockedPair.objects.create(blocker_id=blocker, blocked_id=viewer)

    resp = client_for(viewer).get(reverse("posts:post-comments", args=[post.id]))
    assert [c["id"] for c in resp.json()["data"]] == [str(visible.id)]


def test_cannot_reply_to_a_blocked_author(client_for):
    viewer, other = _acct(), _acct()
    post = services.create_post(viewer, body="p")
    parent = services.add_comment(other, str(post.id), "hi")
    BlockedPair.objects.create(blocker_id=other, blocked_id=viewer)
    resp = client_for(viewer).post(
        reverse("posts:comment-replies", args=[parent.id]), {"body": "x"}, format="json"
    )
    assert resp.status_code == 404


def test_reply_event_names_the_parent_author():
    post_author, parent_author, replier = _acct(), _acct(), _acct()
    post = services.create_post(post_author, body="p")
    parent = services.add_comment(parent_author, str(post.id), "c")
    services.add_comment(replier, str(post.id), "r", str(parent.id))

    payload = OutboxEvent.objects.get(event_type="comment.replied").payload["payload"]
    assert payload["parent_author_id"] == parent_author
    assert payload["post_author_id"] == post_author


def test_only_a_new_reaction_emits_an_event():
    author, reactor = _acct(), _acct()
    post = services.create_post(author, body="p")
    services.react(reactor, str(post.id), "like")
    services.react(reactor, str(post.id), "love")
    assert OutboxEvent.objects.filter(event_type="post.reacted").count() == 1
    assert Post.objects.get(id=post.id).reaction_count == 1


def test_saved_list_is_paged(client_for):
    me = _acct()
    for _ in range(5):
        services.save_item(me, "post", _acct())
    got = _walk(client_for(me), reverse("posts:saved-list") + "?item_type=post")
    assert len({s["item_id"] for s in got}) == 5


def test_batch_queries_do_not_grow_with_posts(client_for):
    viewer = _acct()
    client = client_for(viewer)

    def batch(posts):
        with CaptureQueriesContext(connection) as ctx:
            resp = client.post(
                reverse("posts:post-batch"), {"ids": [str(p.id) for p in posts]}, format="json"
            )
        assert resp.status_code == 200
        return len(ctx)

    posts = [services.create_post(_acct(), body="p", media_ids=[_acct()])]
    few = batch(posts)
    posts += [services.create_post(_acct(), body="p", media_ids=[_acct()]) for _ in range(6)]
    assert batch(posts) == few


def test_purge_removes_only_old_published_and_processed_rows():
    old = timezone.now() - timedelta(days=8)
    services.create_post(_acct(), body="a")
    services.create_post(_acct(), body="b")
    services.create_post(_acct(), body="c")
    published_old, published_new, parked = OutboxEvent.objects.order_by("created_at")
    OutboxEvent.objects.filter(pk=published_old.pk).update(created_at=old, published_at=old)
    OutboxEvent.objects.filter(pk=published_new.pk).update(published_at=timezone.now())
    OutboxEvent.objects.filter(pk=parked.pk).update(created_at=old, attempts=8)

    stale = ProcessedEvent.objects.create(event_id=uuid.uuid4(), consumer="c")
    ProcessedEvent.objects.filter(pk=stale.pk).update(processed_at=old)
    fresh = ProcessedEvent.objects.create(event_id=uuid.uuid4(), consumer="c")

    assert purge_events() == {"outbox": 1, "processed": 1}
    assert set(OutboxEvent.objects.values_list("pk", flat=True)) == {published_new.pk, parked.pk}
    assert list(ProcessedEvent.objects.values_list("pk", flat=True)) == [fresh.pk]
