"""Event consumers for the Social Graph service."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils.dateparse import parse_datetime

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from .models import (
    AccountRef,
    BlockRelation,
    CloseFriendRelation,
    DismissedSuggestion,
    FavoriteRelation,
    FollowRelation,
    Friendship,
    MuteRelation,
    PageRef,
    RelationshipSettings,
    RestrictRelation,
)

logger = logging.getLogger("tara.graph.handlers")


@on_event("account.registered")
def on_account_registered(event: EventEnvelope) -> None:
    """Track known accounts so the graph can resolve/validate targets locally."""
    AccountRef.objects.get_or_create(account_id=event.subject_id)
    logger.debug("account ref recorded", extra={"account_id": event.subject_id})


@on_event("profile.updated")
def on_profile_updated(event: EventEnvelope) -> None:
    """Keep the cached handle fresh, and copy profile's discoverability flag
    (``searchable``, roadmap 1.6) when the event carries it."""
    defaults: dict = {}
    handle = event.payload.get("handle")
    if handle:
        defaults["handle"] = handle
    searchable = event.payload.get("searchable")
    if isinstance(searchable, bool):
        defaults["searchable"] = searchable
    if defaults:
        AccountRef.objects.update_or_create(account_id=event.subject_id, defaults=defaults)


def _occurred(event: EventEnvelope) -> datetime | None:
    return parse_datetime(event.occurred_at or "") if event.occurred_at else None


def _set_flag(event: EventEnvelope, flag: str, value: bool) -> bool:
    """Set ``deactivated`` or ``suspended`` on the account ref, newest event
    wins (an older redelivery never undoes a newer state), and recompute
    ``active``. Returns whether the row changed."""
    try:
        account_id = uuid.UUID(str(event.payload.get("account_id") or event.subject_id))
    except ValueError:
        logger.warning("lifecycle event without a valid account id", extra={"flag": flag})
        return False
    return set_lifecycle(account_id, flag, value, _occurred(event))


def set_lifecycle(account_id, flag: str, value: bool, at: datetime | None) -> bool:
    """The writer behind the lifecycle events and identity's backfill
    (``intel_backfill_accounts``, which passes the export's ``as_of``)."""
    if flag not in ("deactivated", "suspended"):
        raise ValueError(flag)
    stamp = f"{flag}_event_at"
    with transaction.atomic():
        row, _ = AccountRef.objects.select_for_update().get_or_create(account_id=account_id)
        seen = getattr(row, stamp)
        if seen is not None and at is not None and at <= seen:
            return False
        setattr(row, flag, value)
        setattr(row, stamp, at or seen)
        row.active = not (row.deactivated or row.suspended)
        row.save(update_fields=[flag, stamp, "active"])
    return True


@on_event("account.deactivated")
def on_account_deactivated(event: EventEnvelope) -> None:
    """D5: a deactivated account leaves people suggestions and fan-out."""
    _set_flag(event, "deactivated", True)


@on_event("account.reactivated")
def on_account_reactivated(event: EventEnvelope) -> None:
    _set_flag(event, "deactivated", False)


@on_event("account.suspended")
def on_account_suspended(event: EventEnvelope) -> None:
    _set_flag(event, "suspended", True)


@on_event("account.unsuspended")
def on_account_unsuspended(event: EventEnvelope) -> None:
    _set_flag(event, "suspended", False)


#: ``moderation.actioned`` actions on a user that graph applies (rule E11).
RESTRICTING_ACTIONS = frozenset({"restrict", "shadow"})


@on_event("moderation.actioned")
def on_moderation_actioned(event: EventEnvelope) -> None:
    """Rule E11 (D14): an account under ``restrict`` or ``shadow`` leaves people
    suggestions; ``reinstate`` (moderation WP 3.3b, an overturned appeal with
    no other restriction standing) lifts it. ``warn`` and ``dismiss`` change
    nothing, and other target types are not graph's. Newest event wins."""
    p = event.payload if isinstance(event.payload, dict) else {}
    action = p.get("action")
    if p.get("target_type") != "user" or action not in (RESTRICTING_ACTIONS | {"reinstate"}):
        return
    try:
        account_id = uuid.UUID(str(p.get("target_id") or ""))
    except ValueError:
        return
    if set_restriction(account_id, action, p.get("case_id"), _occurred(event)):
        logger.info("account restriction applied", extra={"action": action})


def set_restriction(account_id, action: str, case_id, at: datetime | None) -> bool:
    """The writer behind ``moderation.actioned`` and moderation's backfill
    (``intel_backfill_restrictions``, which passes the export's ``as_of``):
    ``restrict`` / ``shadow`` set it, ``reinstate`` clears it, newest wins."""
    if action not in (RESTRICTING_ACTIONS | {"reinstate"}):
        raise ValueError(action)
    with transaction.atomic():
        row, _ = AccountRef.objects.select_for_update().get_or_create(account_id=account_id)
        seen = row.restriction_event_at
        if seen is not None and at is not None and at <= seen:
            return False
        row.restriction = "" if action == "reinstate" else action
        row.restriction_case_id = _uuid_or_none(case_id)
        row.restriction_event_at = at or seen
        row.save(update_fields=["restriction", "restriction_case_id", "restriction_event_at"])
    return True


def _uuid_or_none(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def apply_page_state(page_id: str, payload: dict, occurred_at: datetime | None) -> bool:
    """Upsert the page read model from a ``page.created``/``page.updated``
    payload (or the same shape from profile's export). An older state than the
    stored one is ignored, so a redelivered event never undoes a newer edit."""
    with transaction.atomic():
        row = PageRef.objects.select_for_update().filter(page_id=page_id).first()
        if (
            row is not None
            and row.source_occurred_at
            and occurred_at
            and occurred_at <= row.source_occurred_at
        ):
            return False
        fields = {
            "handle": str(payload.get("handle") or "")[:64],
            "name": str(payload.get("name") or "")[:160],
            "category": str(payload.get("category") or "")[:80],
            "owner_id": _uuid_or_none(payload.get("owner")),
            "avatar_media_id": _uuid_or_none(payload.get("avatar_media_id")),
            "status": str(payload.get("status") or "published")[:16],
            "deleted": bool(payload.get("deleted")),
            "source_occurred_at": occurred_at,
        }
        PageRef.objects.update_or_create(page_id=page_id, defaults=fields)
    return True


@on_event("page.created")
@on_event("page.updated")
def on_page_changed(event: EventEnvelope) -> None:
    """The "Suggested pages" widget reads published, live pages from here."""
    apply_page_state(event.subject_id, event.payload, parse_datetime(event.occurred_at or ""))


@on_event("account.deleted")
def on_account_deleted(event: EventEnvelope) -> None:
    """Erase the account from the social graph, idempotently (identity 3C):
    friendships and requests, follows both ways (pages included), blocks both
    ways, its mutes, restricts, favorites, close friends and dismissed
    suggestions, and the same lists of others that name it, its relationship
    settings and its account ref. No events: the account is gone, and every
    service drops its own copy on ``account.deleted``.

    What remains: pages it owns keep their ref (a page is not the person's).
    """
    account_id = str(event.payload.get("account_id") or event.subject_id)
    with transaction.atomic():
        Friendship.objects.filter(
            Q(account_low_id=account_id) | Q(account_high_id=account_id)
        ).delete()
        FollowRelation.objects.filter(Q(follower_id=account_id) | Q(target_id=account_id)).delete()
        BlockRelation.objects.filter(Q(blocker_id=account_id) | Q(blocked_id=account_id)).delete()
        for model in (MuteRelation, RestrictRelation, FavoriteRelation, DismissedSuggestion):
            model.objects.filter(Q(account_id=account_id) | Q(target_id=account_id)).delete()
        CloseFriendRelation.objects.filter(
            Q(account_id=account_id) | Q(friend_id=account_id)
        ).delete()
        RelationshipSettings.objects.filter(account_id=account_id).delete()
        AccountRef.objects.filter(account_id=account_id).delete()
    logger.info("graph erased", extra={"account_id": account_id})
