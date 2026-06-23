"""Emit Profile domain events through the outbox."""

from __future__ import annotations

from typing import Any

from tara_events.envelope import EventEnvelope
from tara_events.outbox import record_event

from .models import OutboxEvent

PRODUCER = "profile-service"


def emit(
    event_type: str, *, subject_id: str, payload: dict[str, Any], actor_id: str | None = None
) -> None:
    record_event(
        OutboxEvent,
        EventEnvelope(
            event_type=event_type,
            payload=payload,
            subject_id=str(subject_id),
            producer=PRODUCER,
            actor_id=str(actor_id) if actor_id else None,
        ),
    )
