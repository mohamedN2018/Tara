"""WP 2.5: every domain event writes exactly one ``source=bus`` row, redelivery included."""

import uuid

import feed.handlers  # noqa: F401 - feed's handlers sit next to intel's, as in the consumer
import pytest

import intel.handlers  # noqa: F401
from intel.models import SyntheticAccount

from .helpers import acct, deliver, event, signal_rows

pytestmark = pytest.mark.django_db

ACTOR, POST, AUTHOR, TARGET = acct(), str(uuid.uuid4()), acct(), acct()
COMMENT = str(uuid.uuid4())

CASES = [
    (
        "post.reacted",
        {"post_id": POST, "reactor": ACTOR, "reaction_type": "like", "author_id": AUTHOR},
        ("post_like", "post", POST, AUTHOR),
    ),
    (
        "post.unreacted",
        {"post_id": POST, "reactor": ACTOR, "reaction_type": "like", "author_id": AUTHOR},
        ("post_unlike", "post", POST, AUTHOR),
    ),
    (
        "post.commented",
        {"post_id": POST, "comment_id": COMMENT, "author": ACTOR, "post_author_id": AUTHOR},
        ("post_comment", "post", POST, AUTHOR),
    ),
    (
        "comment.replied",
        {"post_id": POST, "comment_id": COMMENT, "author": ACTOR, "post_author_id": AUTHOR},
        ("post_comment", "post", POST, AUTHOR),
    ),
    (
        "post.shared",
        {"post_id": POST, "share_post_id": COMMENT, "sharer": ACTOR, "author_id": AUTHOR},
        ("post_share", "post", POST, AUTHOR),
    ),
    (
        "post.saved",
        {
            "post_id": POST,
            "account_id": ACTOR,
            "author_id": AUTHOR,
            "saved_at": "2026-11-05T10:00Z",
        },
        ("post_save", "post", POST, AUTHOR),
    ),
    (
        "post.unsaved",
        {
            "post_id": POST,
            "account_id": ACTOR,
            "author_id": AUTHOR,
            "saved_at": "2026-11-05T10:00Z",
        },
        ("post_unsave", "post", POST, AUTHOR),
    ),
    (
        "post.reported",
        {"post_id": POST, "reporter": ACTOR, "reason": "spam", "owner_id": AUTHOR},
        ("post_report", "post", POST, AUTHOR),
    ),
    (
        "user.followed",
        {"follower": ACTOR, "target": TARGET, "target_type": "user"},
        ("follow", "profile", TARGET, TARGET),
    ),
    (
        "user.followed",
        {"follower": ACTOR, "target": TARGET, "target_type": "page"},
        ("follow", "page", TARGET, TARGET),
    ),
    (
        "user.unfollowed",
        {"follower": ACTOR, "target": TARGET, "target_type": "user", "reason": "user"},
        ("unfollow", "profile", TARGET, TARGET),
    ),
    (
        "relationship.muted",
        {"actor_id": ACTOR, "target_id": TARGET},
        ("mute", "profile", TARGET, TARGET),
    ),
    (
        "relationship.unmuted",
        {"actor_id": ACTOR, "target_id": TARGET},
        ("unmute", "profile", TARGET, TARGET),
    ),
    (
        "user.blocked",
        {"blocker_id": ACTOR, "blocked_id": TARGET},
        ("block", "profile", TARGET, TARGET),
    ),
    (
        "user.unblocked",
        {"blocker_id": ACTOR, "blocked_id": TARGET},
        ("unblock", "profile", TARGET, TARGET),
    ),
]


@pytest.mark.parametrize(("event_type", "payload", "expected"), CASES)
def test_one_row_per_event_even_when_redelivered(event_type, payload, expected):
    env = event(event_type, payload, actor=ACTOR)
    deliver(env, times=3, only_intel=True)
    rows = signal_rows(account_id=ACTOR)
    assert len(rows) == 1
    row = rows[0]
    signal, item_type, item, author = expected
    assert (row["event_type"], row["item_type"], str(row["item_id"])) == (signal, item_type, item)
    assert str(row["author_id"]) == author
    assert row["source"] == "bus" and row["data_origin"] == "real" and row["attributed"] is False
    assert row["session_id"] is None and row["cfg_version"] is None


def test_occurred_at_comes_from_the_event():
    from datetime import UTC, datetime

    at = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
    deliver(
        event("relationship.muted", {"actor_id": ACTOR, "target_id": TARGET}, at=at),
        only_intel=True,
    )
    row = signal_rows(account_id=ACTOR)[0]
    assert row["occurred_at"] == at
    assert row["received_at"] > at  # partitioned and retained by receive time


def test_event_without_ids_writes_nothing():
    deliver(event("post.reacted", {"post_id": POST, "author_id": AUTHOR}), only_intel=True)
    assert signal_rows(item_id=POST) == []


def test_bus_rows_of_a_synthetic_account(settings):
    from intel import origin

    settings.INTEL_ACCEPT_SYNTHETIC = True
    seed = acct()
    SyntheticAccount.objects.create(account_id=seed, label="seed-test")
    origin.clear_cache()
    deliver(event("user.blocked", {"blocker_id": seed, "blocked_id": acct()}), only_intel=True)
    assert [r["data_origin"] for r in signal_rows(account_id=seed)] == ["synthetic"]

    settings.INTEL_ACCEPT_SYNTHETIC = False
    deliver(event("user.unblocked", {"blocker_id": seed, "blocked_id": acct()}), only_intel=True)
    assert len(signal_rows(account_id=seed)) == 1  # refused: never stored as real
