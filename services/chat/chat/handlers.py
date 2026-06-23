"""Event consumers for the Chat service."""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services
from .models import BlockedPair


@on_event("marketplace.contact.requested")
def on_marketplace_contact(event: EventEnvelope) -> None:
    """A buyer contacted a seller -> open (or reuse) their marketplace thread."""
    p = event.payload
    services.create_marketplace_conversation(p["buyer_id"], p["seller_id"], p["listing_id"])


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.get_or_create(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"])


@on_event("user.unblocked")
def on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()
