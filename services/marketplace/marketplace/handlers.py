"""Event consumers for the Marketplace service."""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services
from .models import BlockedPair


@on_event("moderation.actioned")
def on_moderation_actioned(event: EventEnvelope) -> None:
    p = event.payload
    if p.get("target_type") == "listing" and p.get("target_id"):
        services.apply_moderation(
            p["target_id"], p.get("action", ""), p.get("case_id"), p.get("reason") or ""
        )
    elif p.get("target_type") == "listing_review" and p.get("target_id"):
        services.apply_review_moderation(p["target_id"], p.get("action", ""))


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.get_or_create(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"])


@on_event("user.unblocked")
def on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()
