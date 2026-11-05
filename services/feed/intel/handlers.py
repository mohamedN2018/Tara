"""Tara Intelligence event handlers, registered in feed's consumer (``consume_events``).

WP 2.5: domain events the client must never report (reactions, comments, shares,
saves, reports, follows, mutes, blocks) become ``intel_signal_event`` rows with
``source=bus``: exactly one row per event, redelivery included, because the worker
runs each handler once per event id (``ProcessedEvent``, keyed by the handler's
name; every name here starts with ``intel_`` so it never collides with feed's).

WP 2.10: ``account.deleted`` erases every ``intel_*`` row of the account and its
``redis-hot`` keys, and takes its posts out of every discovery pool at once.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import deletion, origin
from .models import EventType, ItemType, SignalSource
from .signals import store

logger = logging.getLogger("tara.intel.handlers")


def _when(event: EventEnvelope):
    from feed.services import occurred_at  # one parser for every feed handler

    return occurred_at(event.occurred_at)


def _record(
    event: EventEnvelope,
    event_type: str,
    account_id,
    item_type: str,
    item_id,
    author_id=None,
) -> bool:
    """One bus row for ``account_id``. False when nothing is stored (missing ids, or a
    registered synthetic account in an environment that refuses synthetic rows)."""
    if not account_id or not item_id:
        logger.warning("bus signal without ids; skipped", extra={"event_type": event.event_type})
        return False
    resolution = origin.resolve(account_id)
    if resolution.refused:
        return False
    with transaction.atomic():
        store.insert_row(
            store.SignalRow(
                account_id=account_id,
                event_type=event_type,
                item_type=item_type,
                item_id=item_id,
                author_id=author_id or None,
                source=SignalSource.BUS,
                data_origin=resolution.origin,
                occurred_at=_when(event),
                received_at=timezone.now(),
            )
        )
    return True


def _target_kind(target_type: str | None) -> str:
    return ItemType.PAGE if target_type == "page" else ItemType.PROFILE


@on_event("post.reacted")
def intel_on_post_reacted(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_LIKE,
        p.get("reactor"),
        ItemType.POST,
        p.get("post_id"),
        p.get("author_id"),
    )


@on_event("post.unreacted")
def intel_on_post_unreacted(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_UNLIKE,
        p.get("reactor"),
        ItemType.POST,
        p.get("post_id"),
        p.get("author_id"),
    )


@on_event("post.commented")
def intel_on_post_commented(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_COMMENT,
        p.get("author"),
        ItemType.POST,
        p.get("post_id"),
        p.get("post_author_id"),
    )


@on_event("comment.replied")
def intel_on_comment_replied(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_COMMENT,
        p.get("author"),
        ItemType.POST,
        p.get("post_id"),
        p.get("post_author_id"),
    )


@on_event("post.shared")
def intel_on_post_shared(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_SHARE,
        p.get("sharer"),
        ItemType.POST,
        p.get("post_id"),
        p.get("author_id"),
    )


@on_event("post.saved")
def intel_on_post_saved(event: EventEnvelope) -> None:
    """``post.saved`` (post, behind ``POST_EMIT_SAVE_EVENTS``): ids only, feed only."""
    p = event.payload
    _record(
        event,
        EventType.POST_SAVE,
        p.get("account_id"),
        ItemType.POST,
        p.get("post_id"),
        p.get("author_id"),
    )


@on_event("post.unsaved")
def intel_on_post_unsaved(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_UNSAVE,
        p.get("account_id"),
        ItemType.POST,
        p.get("post_id"),
        p.get("author_id"),
    )


@on_event("post.reported")
def intel_on_post_reported(event: EventEnvelope) -> None:
    """The reporter's own signal. Reporter ids never surface in any per-author view."""
    p = event.payload
    _record(
        event,
        EventType.POST_REPORT,
        p.get("reporter"),
        ItemType.POST,
        p.get("post_id"),
        p.get("owner_id"),
    )


@on_event("user.followed")
def intel_on_user_followed(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.FOLLOW,
        p.get("follower"),
        _target_kind(p.get("target_type")),
        p.get("target"),
        p.get("target"),
    )


@on_event("user.unfollowed")
def intel_on_user_unfollowed(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.UNFOLLOW,
        p.get("follower"),
        _target_kind(p.get("target_type")),
        p.get("target"),
        p.get("target"),
    )


@on_event("relationship.muted")
def intel_on_relationship_muted(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.MUTE,
        p.get("actor_id"),
        ItemType.PROFILE,
        p.get("target_id"),
        p.get("target_id"),
    )


@on_event("relationship.unmuted")
def intel_on_relationship_unmuted(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.UNMUTE,
        p.get("actor_id"),
        ItemType.PROFILE,
        p.get("target_id"),
        p.get("target_id"),
    )


@on_event("user.blocked")
def intel_on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.BLOCK,
        p.get("blocker_id"),
        ItemType.PROFILE,
        p.get("blocked_id"),
        p.get("blocked_id"),
    )


@on_event("user.unblocked")
def intel_on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.UNBLOCK,
        p.get("blocker_id"),
        ItemType.PROFILE,
        p.get("blocked_id"),
        p.get("blocked_id"),
    )


@on_event("account.deleted")
def intel_on_account_deleted(event: EventEnvelope) -> None:
    """Erase the account from Tara Intelligence (idempotent; Redis down -> retried)."""
    account_id = event.payload.get("account_id") or event.subject_id
    counts = deletion.erase_account(account_id)
    logger.info("intel erased account", extra={"account_id": str(account_id), **counts})
