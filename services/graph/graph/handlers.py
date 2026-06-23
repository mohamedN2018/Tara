"""Event consumers for the Social Graph service."""

from __future__ import annotations

import logging

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from .models import AccountRef

logger = logging.getLogger("tara.graph.handlers")


@on_event("account.registered")
def on_account_registered(event: EventEnvelope) -> None:
    """Track known accounts so the graph can resolve/validate targets locally."""
    AccountRef.objects.get_or_create(account_id=event.subject_id)
    logger.debug("account ref recorded", extra={"account_id": event.subject_id})


@on_event("profile.updated")
def on_profile_updated(event: EventEnvelope) -> None:
    """Keep the cached handle fresh for suggestions/search joins."""
    handle = event.payload.get("handle")
    if handle:
        AccountRef.objects.update_or_create(
            account_id=event.subject_id, defaults={"handle": handle}
        )
