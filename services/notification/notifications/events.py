"""Emit notification.created through the outbox (Realtime pushes it to sockets)."""

from __future__ import annotations

from typing import Any

from tara_events.envelope import EventEnvelope
from tara_events.outbox import record_event

from .models import OutboxEvent

PRODUCER = "notification-service"


def emit(event_type: str, *, subject_id: str, payload: dict[str, Any], partition_key: str) -> None:
    record_event(
        OutboxEvent,
        EventEnvelope(
            event_type=event_type,
            payload=payload,
            subject_id=str(subject_id),
            producer=PRODUCER,
            partition_key=partition_key,
        ),
    )
