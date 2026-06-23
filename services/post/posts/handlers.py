"""Event consumers for the Post service."""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from .models import BlockedPair


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.get_or_create(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"])


@on_event("user.unblocked")
def on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()
