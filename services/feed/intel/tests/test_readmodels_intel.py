"""WP 3.1: the phase-3 read models are idempotent and newest-wins.

Every event is delivered twice (the worker's redelivery) and, where order matters,
in both orders: the newest event decides, an older replay changes nothing.
"""

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from feed.models import AuthorRef

import intel.handlers  # noqa: F401 - registers the read-model handlers
from intel import readmodels
from intel.models import (
    AccountRestriction,
    BlockPair,
    ContentRef,
    FriendEdge,
    GroupMembership,
    GroupRef,
    MediaRef,
    PageRef,
)

from .helpers import acct, deliver, event

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def send(event_type, payload, minutes, times=2):
    deliver(event(event_type, payload, at=at(minutes)), times=times, only_intel=True)


def created(author=None, **extra):
    post_id = str(uuid.uuid4())
    payload = {
        "post_id": post_id,
        "author_id": author or acct(),
        "author_type": "user",
        "type": "text",
        "audience": "public",
        "excerpt": "Good morning everyone, the weather is lovely today",
        "media_ids": [],
        "hashtags": ["Cairo", "food", "cairo"],
        "created_at": T0.isoformat(),
        **extra,
    }
    return post_id, payload


# ---- intel_content_ref ----------------------------------------------------------------


def test_post_created_builds_the_content_ref():
    post_id, p = created()
    send("post.created", p, 0)
    row = ContentRef.objects.get(post_id=post_id)
    assert (row.audience, row.type, row.author_type, row.state) == (
        "public",
        "text",
        "user",
        "live",
    )
    assert row.hashtags == ["cairo", "food"]
    assert row.lang == "en"
    assert row.approval_state == "approved"  # not a group post
    assert row.moderation_state == "ok"


def test_group_post_takes_its_approval_state_and_is_approved_by_either_event():
    group = str(uuid.uuid4())
    post_id, p = created(audience="group", group_id=group, approval_state="pending")
    send("post.created", p, 0)
    assert ContentRef.objects.get(post_id=post_id).approval_state == "pending"
    send(
        "post.approved",
        {
            "post_id": post_id,
            "group_id": group,
            "author_id": p["author_id"],
            "approved_by": acct(),
            "tagged_ids": [],
        },
        5,
    )
    assert ContentRef.objects.get(post_id=post_id).approval_state == "approved"

    other, p2 = created(audience="group", group_id=group, approval_state="pending")
    # group.post.published may arrive before post.created: approval only moves forward.
    send(
        "group.post.published",
        {
            "post_id": other,
            "group_id": group,
            "author_id": p2["author_id"],
            "handle": "",
            "recipients": [],
            "chunk": 1,
            "chunks": 1,
        },
        5,
    )
    send("post.created", p2, 0)
    assert ContentRef.objects.get(post_id=other).approval_state == "approved"


def test_a_group_post_created_without_an_approval_state_is_not_approved():
    """Fail closed: an older producer that sent no state never makes a group post
    eligible; only post.approved / group.post.published do."""
    post_id, p = created(audience="group", group_id=str(uuid.uuid4()))
    send("post.created", p, 0)
    assert ContentRef.objects.get(post_id=post_id).approval_state == ""


def test_update_is_newest_wins_in_either_order():
    post_id, p = created()
    narrow = {**p, "audience": "friends", "hashtags": ["news"]}
    send("post.updated", narrow, 10)
    send("post.created", p, 0)  # older: refused
    row = ContentRef.objects.get(post_id=post_id)
    assert (row.audience, row.hashtags) == ("friends", ["news"])
    send("post.updated", {**p, "audience": "public"}, 5)  # older than the stored update
    assert ContentRef.objects.get(post_id=post_id).audience == "friends"


def test_delete_wins_over_an_older_replayed_creation():
    post_id, p = created()
    send("post.deleted", {"post_id": post_id, "author_id": p["author_id"]}, 10)
    send("post.created", p, 0)
    assert ContentRef.objects.get(post_id=post_id).state == "deleted"


def test_hidden_and_unhidden_follow_their_own_guard():
    post_id, p = created()
    send("post.created", p, 0)
    send("post.hidden", {"post_id": post_id, "author_id": p["author_id"]}, 10)
    send("post.updated", {**p, "audience": "friends"}, 12)  # an edit never shows a held post
    assert ContentRef.objects.get(post_id=post_id).state == "hidden"
    send("post.unhidden", p, 20)
    send("post.hidden", {"post_id": post_id, "author_id": p["author_id"]}, 15)  # older replay
    row = ContentRef.objects.get(post_id=post_id)
    assert (row.state, row.held) == ("live", False)


def test_reel_state_changed_is_newest_wins():
    post_id, p = created(type="reel")
    send("post.created", p, 0)
    assert ContentRef.objects.get(post_id=post_id).reel_state == "published"
    change = {"post_id": post_id, "author_id": p["author_id"], "from_state": "published"}
    send("reel.state.changed", {**change, "to_state": "media_missing"}, 10)
    send("reel.state.changed", {**change, "to_state": "published"}, 5)  # older
    assert ContentRef.objects.get(post_id=post_id).reel_state == "media_missing"
    send("reel.state.changed", {**change, "to_state": "published"}, 20)
    assert ContentRef.objects.get(post_id=post_id).reel_state == "published"


def test_reports_open_a_case_and_a_decision_closes_it():
    post_id, p = created()
    send("post.created", p, 0)
    for minute in (1, 2, 3):
        send("post.reported", {"post_id": post_id, "reporter_id": acct()}, minute, times=1)
    row = ContentRef.objects.get(post_id=post_id)
    assert (row.pending_reports, row.moderation_open, row.moderation_state) == (3, True, "pending")
    action = {"case_id": str(uuid.uuid4()), "target_type": "post", "target_id": post_id}
    send("moderation.actioned", {**action, "action": "dismiss"}, 10)
    row = ContentRef.objects.get(post_id=post_id)
    assert (row.pending_reports, row.moderation_open, row.moderation_state) == (0, False, "ok")
    send("post.reported", {"post_id": post_id, "reporter_id": acct()}, 8, times=1)  # before it
    assert ContentRef.objects.get(post_id=post_id).pending_reports == 0
    send("moderation.actioned", {**action, "action": "remove"}, 30)
    assert ContentRef.objects.get(post_id=post_id).moderation_state == "removed"


# ---- intel_media_ref ----------------------------------------------------------------


def test_media_processed_keeps_videos_only_with_a_config_quality():
    video = {
        "owner": acct(),
        "kind": "video",
        "variants": ["poster", "hls"],
        "renditions": [360, 720],
        "duration_ms": 30000,
        "width": 720,
        "height": 1280,
        "has_audio": True,
    }
    env = event("media.processed", video, at=at(0))
    deliver(env, times=2, only_intel=True)
    row = MediaRef.objects.get(media_id=env.subject_id)
    assert (row.top_rung, row.has_poster, row.has_audio, row.quality) == (720, True, True, 1.0)
    silent = event(
        "media.processed",
        {**video, "variants": ["hls"], "has_audio": False, "renditions": [480]},
        at=at(0),
    )
    deliver(silent, only_intel=True)
    assert MediaRef.objects.get(media_id=silent.subject_id).quality == pytest.approx(0.5)
    image = event("media.processed", {"owner": acct(), "kind": "image", "variants": []})
    deliver(image, only_intel=True)
    assert not MediaRef.objects.filter(media_id=image.subject_id).exists()


# ---- relationships ------------------------------------------------------------------


def test_friendship_is_stored_both_ways_and_a_removal_is_a_tombstone():
    a, b = acct(), acct()
    send("friendship.accepted", {"a": a, "b": b}, 0)
    assert FriendEdge.objects.filter(active=True).count() == 2
    send("friendship.removed", {"a": a, "b": b, "reason": "unfriend"}, 10)
    send("friendship.accepted", {"a": a, "b": b}, 5)  # an older replay
    assert FriendEdge.objects.filter(active=True).count() == 0
    assert FriendEdge.objects.count() == 2


def test_block_directions_are_independent_and_newest_wins():
    a, b = acct(), acct()
    send("user.blocked", {"blocker_id": a, "blocked_id": b}, 0)
    send("user.blocked", {"blocker_id": b, "blocked_id": a}, 1)
    send("user.unblocked", {"blocker_id": a, "blocked_id": b}, 10)
    row = BlockPair.objects.get()
    a_flag = "low_blocks" if a < b else "high_blocks"
    b_flag = "high_blocks" if a < b else "low_blocks"
    assert (getattr(row, a_flag), getattr(row, b_flag)) == (False, True)
    send("user.blocked", {"blocker_id": a, "blocked_id": b}, 5)  # older than the unblock
    assert getattr(BlockPair.objects.get(), a_flag) is False


def test_an_unblock_seen_first_refuses_its_older_block():
    a, b = acct(), acct()
    send("user.unblocked", {"blocker_id": a, "blocked_id": b}, 10)
    send("user.blocked", {"blocker_id": a, "blocked_id": b}, 0)
    row = BlockPair.objects.get()
    assert not (row.low_blocks or row.high_blocks)


def _group(group_id, **extra):
    return {
        "group_id": group_id,
        "handle": "g",
        "name": "G",
        "privacy": "private",
        "category": "food",
        **extra,
    }


def test_group_ref_is_newest_wins_and_a_deletion_is_final():
    g = str(uuid.uuid4())
    send("group.created", _group(g, member_count=3), 0)
    send("group.updated", _group(g, privacy="public", member_count=9), 10)
    send("group.updated", _group(g, privacy="hidden"), 5)  # older
    row = GroupRef.objects.get(group_id=g)
    assert (row.privacy, row.status, row.member_count) == ("public", "active", 9)
    send("group.deleted", _group(g, privacy="public"), 20)
    send("group.updated", _group(g, privacy="public", status="active"), 30)
    assert GroupRef.objects.get(group_id=g).status == "deleted"


def test_group_with_an_unknown_privacy_is_stored_as_hidden():
    g = str(uuid.uuid4())
    send("group.created", _group(g, privacy="secret"), 0)
    assert GroupRef.objects.get(group_id=g).privacy == "hidden"


def test_membership_is_newest_wins():
    g, a = str(uuid.uuid4()), acct()
    member = {"group_id": g, "account_id": a, "role": "member", "action": "joined"}
    send("group.member.changed", {**member, "state": "active", "notify_posts": True}, 0)
    send("group.member.changed", {**member, "state": "banned", "action": "banned"}, 10)
    send("group.member.changed", {**member, "state": "active"}, 5)  # older
    row = GroupMembership.objects.get(group_id=g, account_id=a)
    assert (row.state, row.notify_posts, row.joined_at) == ("banned", False, None)


def test_page_ref_and_the_page_author_kind():
    page = str(uuid.uuid4())
    owner = acct()
    body = {
        "handle": "p",
        "name": "P",
        "owner": owner,
        "category": "food",
        "location": "",
        "avatar_media_id": None,
        "changed": [],
    }
    for event_type, status, deleted, minute in (
        ("page.created", "draft", False, 0),
        ("page.updated", "published", False, 10),
        ("page.updated", "suspended", False, 5),  # older
    ):
        env = event(event_type, {**body, "status": status, "deleted": deleted}, at=at(minute))
        env = dataclasses.replace(env, subject_id=page)
        deliver(env, times=2, only_intel=True)
    row = PageRef.objects.get(page_id=page)
    assert (row.status, row.deleted, str(row.owner_id)) == ("published", False, owner)
    assert AuthorRef.objects.get(account_id=page).kind == "page"


# ---- author lifecycle (author_ref) --------------------------------------------------


def test_deactivation_and_suspension_are_separate_flags():
    a = acct()
    send("account.deactivated", {"account_id": a}, 0)
    send("account.suspended", {"account_id": a}, 1)
    send("account.reactivated", {"account_id": a}, 10)
    assert AuthorRef.objects.get(account_id=a).active is False  # still suspended
    send("account.unsuspended", {"account_id": a}, 11)
    send("account.deactivated", {"account_id": a}, 5)  # older than the reactivation
    assert AuthorRef.objects.get(account_id=a).active is True


def test_lifecycle_keeps_the_existing_searchable_flag():
    a = acct()
    AuthorRef.objects.create(account_id=a, searchable=False, occurred_at=T0)
    send("account.deactivated", {"account_id": a}, 0)
    row = AuthorRef.objects.get(account_id=a)
    assert (row.searchable, row.active) == (False, False)


# ---- writers ignore what is not a UUID -----------------------------------------------


def test_non_uuid_ids_are_never_stored():
    assert readmodels.content_created({"post_id": "nope"}, T0) is False
    assert readmodels.set_friendship("x", acct(), True, T0) == 0
    assert readmodels.set_block(acct(), "y", True, T0) is False
    assert readmodels.set_restriction("z", "restrict", None, True, T0) is False
    assert not ContentRef.objects.exists()
    assert not AccountRestriction.objects.exists()
