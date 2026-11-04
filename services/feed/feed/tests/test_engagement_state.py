"""Engagement counters under retries and deletes (review wave 2, findings #0-#2).

#0  ``feed_item`` has a ``post_id`` index, and a flag hide never rewrites every
    recipient's feed row inside the request (the refresh runs after the commit).
#1  Reactions are counted per (post, reactor), newest event wins: an unreact
    handled before its retried react leaves nothing counted.
#2  ``comment.deleted`` / ``comment.restored`` move ``PostStats.comments`` once
    per comment, whatever the order or redelivery.
"""

import importlib
import uuid
from datetime import timedelta

import pytest
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from feed import handlers, ranking  # noqa: F401 - registers the consumers
from feed.models import Affinity, FeedItem, PostStats, ProcessedEvent
from tara_events.consumer import idempotent
from tara_events.dispatch import handlers_for
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _id() -> str:
    return str(uuid.uuid4())


def _item(viewer, author, *, post_id=None, minutes_ago=0):
    post_id = post_id or _id()
    return FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason="follow",
        snapshot={"post_id": post_id, "author_id": author, "audience": "public"},
        post_created_at=timezone.now() - timedelta(minutes=minutes_ago),
    )


def _event(event_type, payload, at) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        subject_id=payload.get("comment_id") or payload["post_id"],
        producer="post-service",
        payload=payload,
        occurred_at=at.isoformat(),
    )


def _deliver(event: EventEnvelope) -> None:
    """As the worker does: each handler runs once per event id."""
    for fn in handlers_for(event.event_type):
        with idempotent(ProcessedEvent, event.event_id, f"feed:{fn.__name__}") as fresh:
            if fresh:
                fn(event)


def _stats(post_id) -> PostStats:
    return PostStats.objects.filter(post_id=post_id).first() or PostStats(post_id=post_id)


def _affinity(account, author) -> int:
    row = Affinity.objects.filter(account_id=account, author_id=author).first()
    return row.interactions if row else 0


# ---- #0: the post_id index and no mass rewrite in the hide request --------------


def test_feed_item_has_an_index_on_post_id():
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, "feed_item")
    assert any(c["index"] and c["columns"] == ["post_id"] for c in constraints.values())


def test_the_post_id_index_is_built_concurrently():
    migration = importlib.import_module("feed.migrations.0006_feed_item_post_idx").Migration
    assert migration.atomic is False
    assert [type(op) for op in migration.operations] == [AddIndexConcurrently]


def test_a_flag_hide_counts_now_and_refreshes_feed_rows_after_the_commit(
    client_for, django_capture_on_commit_callbacks
):
    author, viewer, other = _id(), _id(), _id()
    post = _id()
    for v in (viewer, other, _id()):
        _item(v, author, post_id=post)
    plain = _item(other, author, minutes_ago=30)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        with CaptureQueriesContext(connection) as queries:
            resp = client_for(viewer).post(
                reverse("feed:hide"), {"post_id": post, "reason": "spam"}
            )
    assert resp.status_code < 300
    rewrites = [q["sql"] for q in queries if q["sql"].startswith('UPDATE "feed_item"')]
    assert rewrites == []
    assert _stats(post).flags == 1
    assert set(FeedItem.objects.filter(post_id=post).values_list("score", flat=True)) == {0.0}
    # The ranking reads the live counters: the flagged post already ranks lower.
    ranked = [str(i.post_id) for i in ranking.rank_items(other, timezone.now())]
    assert ranked == [str(plain.post_id), post]

    for callback in callbacks:  # the commit: feed.refresh_post_score (eager in tests)
        callback()
    assert all(s < 0 for s in FeedItem.objects.filter(post_id=post).values_list("score", flat=True))

    with django_capture_on_commit_callbacks(execute=True):
        client_for(viewer).delete(reverse("feed:unhide", args=[post]))
    assert _stats(post).flags == 0
    assert set(FeedItem.objects.filter(post_id=post).values_list("score", flat=True)) == {0.0}


# ---- #1: reactions are order-independent ----------------------------------------


def _reaction(kind, post, reactor, author, at):
    return _event(
        kind,
        {"post_id": post, "reactor": reactor, "reaction_type": "like", "author_id": author},
        at,
    )


def test_an_unreact_handled_before_its_react_leaves_nothing_counted():
    author, reactor, viewer = _id(), _id(), _id()
    post = str(_item(viewer, author).post_id)
    t = timezone.now() - timedelta(minutes=5)
    reacted = _reaction("post.reacted", post, reactor, author, t)
    unreacted = _reaction("post.unreacted", post, reactor, author, t + timedelta(seconds=1))

    _deliver(unreacted)  # the react failed once and sits in the retry queue
    _deliver(reacted)

    assert _stats(post).reactions == 0
    assert _affinity(reactor, author) == 0
    assert FeedItem.objects.get(post_id=post).score == 0.0


def test_reordered_reactions_from_two_people_count_only_the_live_one():
    author, a, b = _id(), _id(), _id()
    post = _id()
    t = timezone.now() - timedelta(minutes=5)
    _deliver(_reaction("post.reacted", post, a, author, t))
    _deliver(_reaction("post.unreacted", post, b, author, t + timedelta(seconds=2)))
    _deliver(_reaction("post.reacted", post, b, author, t + timedelta(seconds=1)))
    assert _stats(post).reactions == 1
    assert (_affinity(a, author), _affinity(b, author)) == (1, 0)


def test_react_unreact_react_in_order_counts_once():
    author, reactor = _id(), _id()
    post = _id()
    t = timezone.now() - timedelta(minutes=5)
    _deliver(_reaction("post.reacted", post, reactor, author, t))
    _deliver(_reaction("post.unreacted", post, reactor, author, t + timedelta(seconds=1)))
    again = t + timedelta(seconds=2)
    _deliver(_reaction("post.reacted", post, reactor, author, again))
    _deliver(_reaction("post.reacted", post, reactor, author, again))  # a second emission
    assert _stats(post).reactions == 1
    assert _affinity(reactor, author) == 1


# ---- #2: deleted and restored comments ------------------------------------------


def _created(post, comment, author, post_author, at, *, reply=False):
    return _event(
        "comment.replied" if reply else "post.commented",
        {"post_id": post, "comment_id": comment, "author": author, "post_author_id": post_author},
        at,
    )


def _deleted(post, comment, author, post_author, removed, at, by="author"):
    return _event(
        "comment.deleted",
        {
            "post_id": post,
            "comment_id": comment,
            "author_id": author,
            "post_author_id": post_author,
            "parent_id": None,
            "removed_ids": removed,
            "by": by,
        },
        at,
    )


def _restored(post, comment, restored, at):
    return _event(
        "comment.restored",
        {"post_id": post, "comment_id": comment, "restored_ids": restored},
        at,
    )


@pytest.fixture
def thread():
    """A root by ``a`` with replies by ``b`` and ``c`` on ``owner``'s post."""
    owner, a, b, c, viewer = _id(), _id(), _id(), _id(), _id()
    post = str(_item(viewer, owner).post_id)
    root, r1, r2 = _id(), _id(), _id()
    t = timezone.now() - timedelta(minutes=10)
    _deliver(_created(post, root, a, owner, t))
    _deliver(_created(post, r1, b, owner, t + timedelta(seconds=1), reply=True))
    _deliver(_created(post, r2, c, owner, t + timedelta(seconds=2), reply=True))
    assert _stats(post).comments == 3
    return {
        "post": post,
        "owner": owner,
        "authors": (a, b, c),
        "ids": (root, r1, r2),
        "t": t + timedelta(minutes=1),
    }


def test_deleting_a_reply_stops_counting_it(thread):
    post, owner, (_, b, _c), (_, r1, _) = (
        thread["post"],
        thread["owner"],
        thread["authors"],
        thread["ids"],
    )
    score_before = FeedItem.objects.get(post_id=post).score
    deleted = _deleted(post, r1, b, owner, [r1], thread["t"])
    _deliver(deleted)
    _deliver(deleted)  # a redelivery
    assert _stats(post).comments == 2
    assert _affinity(b, owner) == 0
    assert FeedItem.objects.get(post_id=post).score < score_before


def test_deleting_a_root_takes_its_replies_once(thread):
    post, owner, authors, ids = thread["post"], thread["owner"], thread["authors"], thread["ids"]
    _deliver(_deleted(post, ids[0], authors[0], owner, list(ids), thread["t"]))
    # The same removal reported again under a new event id changes nothing.
    _deliver(_deleted(post, ids[0], authors[0], owner, list(ids), thread["t"]))
    assert _stats(post).comments == 0
    assert [_affinity(x, owner) for x in authors] == [0, 0, 0]
    assert FeedItem.objects.get(post_id=post).score == 0.0


def test_a_moderation_removal_then_restore_counts_the_thread_again(thread):
    post, owner, authors, ids = thread["post"], thread["owner"], thread["authors"], thread["ids"]
    t = thread["t"]
    _deliver(_deleted(post, ids[0], authors[0], owner, list(ids), t, by="moderation"))
    assert _stats(post).comments == 0
    restored = _restored(post, ids[0], list(ids), t + timedelta(seconds=5))
    _deliver(restored)
    _deliver(_restored(post, ids[0], list(ids), t + timedelta(seconds=5)))  # new event id
    assert _stats(post).comments == 3
    assert [_affinity(x, owner) for x in authors] == [1, 1, 1]


def test_a_restore_handled_before_its_removal_keeps_the_comments(thread):
    post, owner, authors, ids = thread["post"], thread["owner"], thread["authors"], thread["ids"]
    t = thread["t"]
    removal = _deleted(post, ids[0], authors[0], owner, list(ids), t, by="moderation")
    _deliver(_restored(post, ids[0], list(ids), t + timedelta(seconds=5)))
    _deliver(removal)  # retried, older than the restore
    assert _stats(post).comments == 3


def test_a_delete_handled_before_its_comment_leaves_nothing_counted():
    owner, author = _id(), _id()
    post, comment = _id(), _id()
    t = timezone.now() - timedelta(minutes=5)
    _deliver(_deleted(post, comment, author, owner, [comment], t + timedelta(seconds=1)))
    _deliver(_created(post, comment, author, owner, t))
    assert _stats(post).comments == 0
    assert _affinity(author, owner) == 0
