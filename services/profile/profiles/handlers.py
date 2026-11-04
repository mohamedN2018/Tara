"""Event consumers for the Profile service.

Importing this module registers the handlers (the `consume_events` command does
that). Handlers are invoked under an idempotency guard by the event worker.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from .models import BlockedPair, PageMember, UserProfile
from .services import ensure_profile

logger = logging.getLogger("tara.profile.handlers")


@on_event("account.registered")
def on_account_registered(event: EventEnvelope) -> None:
    """Provision an empty profile when a new account is created."""
    p = event.payload
    # Sign-ups since 1D carry the first and last names; Google and older events
    # carry only display_name.
    full_name = " ".join(n for n in (p.get("first_name", ""), p.get("last_name", "")) if n)
    ensure_profile(
        event.subject_id,
        display_name=(full_name or p.get("display_name", ""))[:80],
        requested_handle=p.get("handle", ""),
    )
    logger.info("profile provisioned", extra={"account_id": event.subject_id})


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.get_or_create(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"])


@on_event("user.unblocked")
def on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()


# ---- account lifecycle (identity, plan 08 3C) ------------------------------------------
# Deactivation (and a deletion's 30-day grace) hides the profile from everyone:
# every read already skips a profile with ``deleted_at`` (404, absent from
# cards, lookups and search exports). Reactivation shows it again, unchanged.
# Nothing else in profile sets ``UserProfile.deleted_at``, so clearing it can
# only undo this hide.


def _account(event: EventEnvelope) -> str:
    return str(event.payload.get("account_id") or event.subject_id)


@on_event("account.deactivated")
def on_account_deactivated(event: EventEnvelope) -> None:
    UserProfile.objects.filter(account_id=_account(event), deleted_at__isnull=True).update(
        deleted_at=timezone.now()
    )


@on_event("account.reactivated")
def on_account_reactivated(event: EventEnvelope) -> None:
    UserProfile.objects.filter(account_id=_account(event), deleted_at__isnull=False).update(
        deleted_at=None
    )


@on_event("account.deleted")
def on_account_deleted(event: EventEnvelope) -> None:
    """Erase the profile for good: the row and, by cascade, its field privacy,
    links, education and work; the account's page roles and block rows.

    What remains: pages the account created stay with their other members (a
    page whose only owner it was keeps no owner until staff reassign it), and
    group memberships in the ``groups`` app keep the bare account id.
    """
    account_id = _account(event)
    with transaction.atomic():
        UserProfile.objects.filter(account_id=account_id).delete()
        PageMember.objects.filter(account_id=account_id).delete()
        BlockedPair.objects.filter(Q(blocker_id=account_id) | Q(blocked_id=account_id)).delete()
    logger.info("profile erased", extra={"account_id": account_id})
