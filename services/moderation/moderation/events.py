"""Emit Moderation domain events (moderation.actioned) through the outbox."""

from __future__ import annotations

from typing import Any

from tara_common.middleware import current_request_id
from tara_events.envelope import EventEnvelope
from tara_events.outbox import record_event

from .models import OutboxEvent

PRODUCER = "moderation-service"


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
            # The edge's request id, so admin's audit log can tie the decision
            # to the request that made it. None from consumers.
            correlation_id=current_request_id(),
        ),
    )
