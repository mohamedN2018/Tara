"""Account deactivation hides a post from every feed and reactivation brings it
back (plan 08 3C): ``post.hidden`` keeps the rows, ``post.unhidden`` shows them
again and fans the post out to anyone missing one."""

import json
import os
import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from feed import handlers  # noqa: F401 - registers the consumers
from feed.models import FeedItem, OutboxEvent, PostState, ProcessedEvent
from tara_events.consumer import idempotent
from tara_events.dispatch import handlers_for
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

SCHEMAS = "/opt/tara/libs/tara_events/tara_events/schemas"
MODES = ("recent", "for_you", "following")
FRIEND_MODES = ("recent", "for_you")  # a friend's row is not a "following" row


def _acct() -> str:
    return str(uuid.uuid4())


def _deliver(event_type: str, payload: dict, at) -> None:
    """As the worker does: each handler runs once per event id."""
    event = EventEnvelope(
        event_type=event_type,
        subject_id=payload["post_id"],
        producer="post-service",
        payload=payload,
        occurred_at=at.isoformat(),
    )
    for fn in handlers_for(event_type):
        with idempotent(ProcessedEvent, event.event_id, f"feed:{fn.__name__}") as fresh:
            if fresh:
                fn(event)


@pytest.fixture(autouse=True)
def no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


@pytest.fixture
def world(monkeypatch):
    """An author with a friend and a follower; ``t`` is the post's creation."""
    author, friend, follower = _acct(), _acct(), _acct()
    audience = {"friends": [friend], "followers": [follower]}
    monkeypatch.setattr("feed.services.fanout_audience", lambda a, **kw: audience)
    t = timezone.now() - timedelta(hours=1)
    post = {
        "post_id": str(uuid.uuid4()),
        "author_id": author,
        "author_type": "user",
        "type": "text",
        "audience": "public",
        "excerpt": "harbour at dawn",
        "media_ids": [],
        "created_at": t.isoformat(),
    }
    return author, friend, follower, post, t


def _hidden(post: dict) -> dict:
    return {
        "post_id": post["post_id"],
        "author_id": post["author_id"],
        "reason": "account_deactivated",
    }


def _unhidden(post: dict) -> dict:
    return {**post, "group_id": None, "reason": "account_reactivated"}


def _seen(client_for, viewer, post_id, modes=MODES) -> dict[str, bool]:
    """Whether the post is on the viewer's first page, per feed mode."""
    client = client_for(viewer)
    out = {}
    for mode in modes:
        resp = client.get(reverse("feed:home-feed"), {"mode": mode, "limit": 50})
        assert resp.status_code == 200, resp.content
        out[mode] = post_id in [i["post_id"] for i in resp.json()["data"]]
    return out


def test_deactivation_hides_the_post_everywhere_and_reactivation_restores_it(client_for, world):
    author, friend, follower, post, t = world
    _deliver("post.created", post, t)
    rows_before = set(FeedItem.objects.filter(post_id=post["post_id"]).values_list("id", flat=True))
    assert len(rows_before) == 3
    assert all(_seen(client_for, friend, post["post_id"], FRIEND_MODES).values())

    _deliver("post.hidden", _hidden(post), t + timedelta(minutes=5))
    for viewer in (author, friend, follower):
        assert not any(_seen(client_for, viewer, post["post_id"]).values()), viewer
    # Kept, not deleted: nothing to rebuild on reactivation.
    assert FeedItem.objects.filter(post_id=post["post_id"]).count() == 3
    # Hiding it from one's own feed is a 404, as for a post that never reached it.
    hide = client_for(friend).post(
        reverse("feed:hide"), {"post_id": post["post_id"], "reason": "not_interested"}
    )
    assert hide.status_code == 404

    added = OutboxEvent.objects.filter(event_type="feed.item.added").count()
    _deliver("post.unhidden", _unhidden(post), t + timedelta(minutes=30))
    rows_after = set(FeedItem.objects.filter(post_id=post["post_id"]).values_list("id", flat=True))
    assert rows_after == rows_before  # the same rows, nothing fanned out twice
    assert OutboxEvent.objects.filter(event_type="feed.item.added").count() == added
    assert all(_seen(client_for, friend, post["post_id"], FRIEND_MODES).values())
    assert all(_seen(client_for, follower, post["post_id"], ("recent", "following")).values())
    assert _seen(client_for, author, post["post_id"])["recent"]


def test_rows_an_older_release_deleted_are_fanned_out_again(world):
    """Before post.hidden, deactivation emitted post.deleted and feed dropped
    every row: post.unhidden from a reactivation now rebuilds them."""
    _, friend, follower, post, t = world
    _deliver("post.created", post, t)
    _deliver("post.deleted", {"post_id": post["post_id"]}, t + timedelta(minutes=5))
    assert not FeedItem.objects.filter(post_id=post["post_id"]).exists()

    _deliver("post.unhidden", _unhidden(post), t + timedelta(minutes=30))
    rows = {str(i.recipient_id): i for i in FeedItem.objects.filter(post_id=post["post_id"])}
    assert set(rows) == {post["author_id"], friend, follower}
    assert rows[friend].snapshot["excerpt"] == "harbour at dawn"
    assert rows[friend].post_created_at.isoformat() == post["created_at"]  # its own date
    state = PostState.objects.get(post_id=post["post_id"])
    assert not state.deleted and not state.hidden


def test_a_hide_retried_after_the_unhide_changes_nothing(client_for, world):
    _, friend, _, post, t = world
    _deliver("post.created", post, t)
    _deliver("post.unhidden", _unhidden(post), t + timedelta(minutes=30))
    _deliver("post.hidden", _hidden(post), t + timedelta(minutes=5))  # older, redelivered late
    assert all(_seen(client_for, friend, post["post_id"], FRIEND_MODES).values())


def test_an_edit_does_not_unhide_and_a_late_creation_stays_hidden(client_for, world):
    _, friend, _, post, t = world
    _deliver("post.hidden", _hidden(post), t + timedelta(minutes=5))
    _deliver("post.created", post, t)  # retried after the hide
    _deliver(
        "post.updated",
        {
            "post_id": post["post_id"],
            "author_id": post["author_id"],
            "audience": "public",
            "excerpt": "edited",
        },
        t + timedelta(minutes=10),
    )
    assert not any(_seen(client_for, friend, post["post_id"]).values())
    _deliver("post.unhidden", {**_unhidden(post), "excerpt": "edited"}, t + timedelta(minutes=30))
    assert all(_seen(client_for, friend, post["post_id"], FRIEND_MODES).values())


def test_a_real_delete_after_reactivation_wins_over_a_late_unhide(world):
    _, _, _, post, t = world
    _deliver("post.created", post, t)
    _deliver("post.hidden", _hidden(post), t + timedelta(minutes=5))
    _deliver("post.deleted", {"post_id": post["post_id"]}, t + timedelta(minutes=40))
    _deliver("post.unhidden", _unhidden(post), t + timedelta(minutes=30))  # older
    assert not FeedItem.objects.filter(post_id=post["post_id"]).exists()
    assert PostState.objects.get(post_id=post["post_id"]).deleted


def test_the_payloads_used_here_match_the_json_schemas(world):
    """Post emits these shapes (posts/tests/test_account_lifecycle.py checks the
    same schemas from the producer side)."""
    if not os.path.isdir(SCHEMAS):
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    _, _, _, post, _ = world
    for name, payload in (("post.hidden", _hidden(post)), ("post.unhidden", _unhidden(post))):
        with open(f"{SCHEMAS}/{name}.v1.json", encoding="utf-8") as f:
            schema = json.load(f)
        assert set(schema["required"]) <= set(payload) <= set(schema["properties"]), name
