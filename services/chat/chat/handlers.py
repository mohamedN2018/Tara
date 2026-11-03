"""Event consumers for the Chat service."""

from __future__ import annotations

from tara_common.exceptions import TaraAPIError
from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services
from .models import BlockedPair


@on_event("marketplace.contact.requested")
def on_marketplace_contact(event: EventEnvelope) -> None:
    """A buyer contacted a seller -> open (or reuse) their marketplace thread."""
    p = event.payload
    try:
        services.create_marketplace_conversation(p["buyer_id"], p["seller_id"], p["listing_id"])
    except TaraAPIError:
        # A blocked pair gets no thread; retrying would only dead-letter the event.
        return


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    _, created = BlockedPair.objects.get_or_create(
        blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]
    )
    if created:
        services.revoke_pair_subscriptions(p["blocker_id"], p["blocked_id"])


@on_event("user.unblocked")
def on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()


@on_event("moderation.actioned")
def on_moderation_actioned(event: EventEnvelope) -> None:
    p = event.payload
    if p.get("target_type") != "message":
        return
    if p.get("action") == "remove":
        services.remove_message(p["target_id"])
    elif p.get("action") in ("approve", "restore"):
        # An overturned removal arrives as `approve` (doc 04, moderation.actioned).
        services.restore_message(p["target_id"])
