"""WP 2.5: every post-menu action (hide, snooze, mute, unfollow, block, report) produces
exactly one signal row, and so does each undo."""

import uuid
from datetime import timedelta

import feed.handlers  # noqa: F401
import pytest
from django.utils import timezone
from feed.models import FeedItem, PostHide

import intel.handlers  # noqa: F401

from .helpers import acct, deliver, event, signal_rows

pytestmark = pytest.mark.django_db


def _row(viewer):
    post_id, author = str(uuid.uuid4()), acct()
    FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason="friend",
        snapshot={"post_id": post_id, "author_id": author, "audience": "public"},
        post_created_at=timezone.now() - timedelta(minutes=1),
    )
    return post_id, author


def _types(viewer):
    return [r["event_type"] for r in signal_rows(account_id=viewer)]


def test_hide_and_undo(client_for):
    viewer = acct()
    post_id, author = _row(viewer)
    c = client_for(viewer)
    assert c.post("/api/v1/feed/hide/", {"post_id": post_id, "reason": "spam"}).status_code == 201
    # A repeat, or a new reason, is the same hide.
    c.post("/api/v1/feed/hide/", {"post_id": post_id, "reason": "annoying"})
    rows = signal_rows(account_id=viewer)
    assert [r["event_type"] for r in rows] == ["post_hide"]
    assert str(rows[0]["item_id"]) == post_id and str(rows[0]["author_id"]) == author
    assert rows[0]["source"] == "server"
    assert c.delete(f"/api/v1/feed/hide/{post_id}/").status_code == 204
    c.delete(f"/api/v1/feed/hide/{post_id}/")  # nothing left to undo
    assert _types(viewer) == ["post_hide", "post_unhide"]


def test_failed_hide_writes_nothing(client_for):
    viewer = acct()
    resp = client_for(viewer).post(
        "/api/v1/feed/hide/", {"post_id": str(uuid.uuid4()), "reason": "spam"}
    )
    assert resp.status_code == 404
    assert _types(viewer) == []


def test_snooze_and_undo(client_for):
    viewer, author = acct(), acct()
    c = client_for(viewer)
    assert c.post("/api/v1/feed/snooze/", {"author_id": author}).status_code == 201
    rows = signal_rows(account_id=viewer)
    assert [(r["event_type"], r["item_type"], str(r["item_id"])) for r in rows] == [
        ("author_snooze", "profile", author)
    ]
    assert c.delete(f"/api/v1/feed/snooze/{author}/").status_code == 204
    c.delete(f"/api/v1/feed/snooze/{author}/")
    assert _types(viewer) == ["author_snooze", "author_unsnooze"]


def test_snoozing_yourself_writes_nothing(client_for):
    viewer = acct()
    assert client_for(viewer).post("/api/v1/feed/snooze/", {"author_id": viewer}).status_code == 400
    assert _types(viewer) == []


def _mute(v, t):
    return {"actor_id": v, "target_id": t}


def _block(v, t):
    return {"blocker_id": v, "blocked_id": t}


def _follow(v, t):
    return {"follower": v, "target": t, "target_type": "user"}


@pytest.mark.parametrize(
    ("action", "undo", "payload", "expected"),
    [
        ("relationship.muted", "relationship.unmuted", _mute, ["mute", "unmute"]),
        ("user.blocked", "user.unblocked", _block, ["block", "unblock"]),
        ("user.unfollowed", "user.followed", _follow, ["unfollow", "follow"]),
    ],
)
def test_graph_menu_actions_and_undo(action, undo, payload, expected):
    viewer, target = acct(), acct()
    deliver(event(action, payload(viewer, target)), times=2)
    deliver(event(undo, payload(viewer, target)), times=2)
    assert _types(viewer) == expected


def test_report_writes_one_row():
    viewer, post_id = acct(), str(uuid.uuid4())
    payload = {"post_id": post_id, "reporter": viewer, "reason": "spam", "owner_id": acct()}
    deliver(event("post.reported", payload), times=2)
    assert _types(viewer) == ["post_report"]


def test_action_and_signal_share_the_transaction(client_for, monkeypatch):
    """The signal row is written in the action's transaction: if it fails, no hide."""
    from intel.signals import store

    viewer = acct()
    post_id, _ = _row(viewer)

    def boom(row):
        raise RuntimeError("signal store down")

    monkeypatch.setattr(store, "insert_row", boom)
    client = client_for(viewer)
    client.raise_request_exception = False
    resp = client.post("/api/v1/feed/hide/", {"post_id": post_id, "reason": "spam"})
    assert resp.status_code == 500
    assert not PostHide.objects.filter(account_id=viewer).exists()
