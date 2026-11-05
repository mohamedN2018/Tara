"""Builders for the retrieval and eligibility tests: rows exactly as the read-model
writers and feed's fan-out store them (no HTTP, no bus)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from feed.models import AuthorRef, FeedItem, FollowEdge, PostHide, RelationshipFlag

from intel import readmodels
from intel.models import (
    AccountRestriction,
    BlockPair,
    ContentRef,
    FanoutCapped,
    GroupMembership,
    GroupRef,
    PageRef,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def uid() -> str:
    return str(uuid.uuid4())


def post(
    author: str,
    *,
    audience: str = "public",
    type: str = "text",  # noqa: A002
    group: str | None = None,
    approval: str = "approved",
    state: str = "live",
    moderation: str = "ok",
    reel_state: str | None = None,
    author_type: str = "user",
    age: timedelta = timedelta(hours=1),
    lang: str = "en",
    pending_reports: int = 0,
    moderation_open: bool = False,
    media_ids: list[str] | None = None,
) -> str:
    post_id = uid()
    ContentRef.objects.create(
        post_id=post_id,
        author_id=author,
        author_type=author_type,
        type=type,
        audience=audience,
        group_id=group,
        approval_state=approval,
        reel_state=reel_state
        if reel_state is not None
        else ("published" if type == "reel" else ""),
        state=state,
        moderation_state=moderation,
        pending_reports=pending_reports,
        moderation_open=moderation_open,
        lang=lang,
        media_ids=media_ids or [],
        created_at=NOW - age,
        event_at=NOW - age,
    )
    return post_id


def feed_row(recipient: str, post_id: str, author: str, reason: str = "friend", *, type="text"):
    created = (
        ContentRef.objects.filter(post_id=post_id).values_list("created_at", flat=True).first()
    )
    FeedItem.objects.create(
        recipient_id=recipient,
        post_id=post_id,
        author_id=author,
        reason=reason,
        snapshot={"type": type},
        post_created_at=created or NOW,
    )


def friends(a: str, b: str, *, since: datetime | None = None) -> None:
    readmodels.set_friendship(a, b, True, since or NOW - timedelta(days=30), since=since)


def follow(follower: str, target: str, *, at: datetime | None = None, target_type="user"):
    FollowEdge.objects.update_or_create(
        follower_id=follower,
        target_id=target,
        defaults={
            "target_type": target_type,
            "active": True,
            "occurred_at": at or NOW - timedelta(days=30),
        },
    )


def block(blocker: str, blocked: str) -> None:
    readmodels.set_block(blocker, blocked, True, NOW - timedelta(days=1))


def group(*, privacy: str = "public", status: str = "active", owner: str | None = None) -> str:
    group_id = uid()
    GroupRef.objects.create(group_id=group_id, privacy=privacy, status=status, event_at=NOW)
    if owner:
        member(owner, group_id, role="owner")
    return group_id


def member(account: str, group_id: str, *, state="active", role="member", notify=False):
    GroupMembership.objects.update_or_create(
        account_id=account,
        group_id=group_id,
        defaults={
            "state": state,
            "role": role,
            "notify_posts": notify,
            "joined_at": NOW if state == "active" else None,
            "event_at": NOW,
        },
    )


def page(owner: str, *, status: str = "published", deleted: bool = False) -> str:
    page_id = uid()
    PageRef.objects.create(
        page_id=page_id, owner_id=owner, status=status, deleted=deleted, event_at=NOW
    )
    AuthorRef.objects.update_or_create(
        account_id=page_id, defaults={"occurred_at": NOW, "kind": "page"}
    )
    return page_id


def author(account: str, *, active=True, searchable=True) -> None:
    AuthorRef.objects.update_or_create(
        account_id=account,
        defaults={"occurred_at": NOW, "active": active, "searchable": searchable},
    )


def restrict(account: str, kind: str = "shadow") -> None:
    AccountRestriction.objects.create(
        account_id=account, kind=kind, active=True, since=NOW, event_at=NOW
    )


def hide(viewer: str, post_id: str, author_id: str, reason: str = "not_interested"):
    PostHide.objects.create(account_id=viewer, post_id=post_id, author_id=author_id, reason=reason)


def mute(viewer: str, target: str):
    RelationshipFlag.objects.create(
        actor_id=viewer,
        target_id=target,
        kind=RelationshipFlag.Kind.MUTE,
        active=True,
        occurred_at=NOW,
    )


def capped(post_id: str, author_id: str, *, total=10, cap=5):
    ref = ContentRef.objects.get(post_id=post_id)
    FanoutCapped.objects.create(
        post_id=post_id,
        author_id=author_id,
        audience=ref.audience,
        total=total,
        cap=cap,
        created_at=ref.created_at,
    )


__all__ = [
    "NOW",
    "BlockPair",
    "author",
    "block",
    "capped",
    "feed_row",
    "follow",
    "friends",
    "group",
    "hide",
    "member",
    "mute",
    "page",
    "post",
    "restrict",
    "uid",
]
