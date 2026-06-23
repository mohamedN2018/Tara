"""Emit Chat domain events through the outbox.

`message.created` carries the conversation's member ids as `recipients` so the
Realtime gateway can push to each member's socket group without its own DB.
"""

from __future__ import annotations

from typing import Any

from tara_events.envelope import EventEnvelope
from tara_events.outbox import record_event

from .models import OutboxEvent

PRODUCER = "chat-service"


def emit(
    event_type: str,
    *,
    subject_id: str,
    payload: dict[str, Any],
    actor_id: str | None = None,
    partition_key: str | None = None,
) -> None:
    record_event(
        OutboxEvent,
        EventEnvelope(
            event_type=event_type,
            payload=payload,
            subject_id=str(subject_id),
            producer=PRODUCER,
            actor_id=str(actor_id) if actor_id else None,
            partition_key=partition_key,
        ),
    )
