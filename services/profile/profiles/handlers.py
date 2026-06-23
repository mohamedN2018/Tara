"""Event consumers for the Profile service.

Importing this module registers the handlers (the `consume_events` command does
that). Handlers are invoked under an idempotency guard by the event worker.
"""

from __future__ import annotations

import logging

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from .models import BlockedPair
from .services import ensure_profile

logger = logging.getLogger("tara.profile.handlers")


@on_event("account.registered")
def on_account_registered(event: EventEnvelope) -> None:
    """Provision an empty profile when a new account is created."""
    ensure_profile(event.subject_id, email=event.payload.get("email", ""))
    logger.info("profile provisioned", extra={"account_id": event.subject_id})


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.get_or_create(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"])


@on_event("user.unblocked")
def on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()
