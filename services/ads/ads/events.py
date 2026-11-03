"""Emit Ads domain events through the outbox.

Impression/click events travel on this path now; at scale they move to a Kafka
firehose (ADR-003). They carry only a coarse viewer bucket — never the raw id.
"""

from __future__ import annotations

from typing import Any

from tara_common.middleware import current_request_id
from tara_events.envelope import EventEnvelope
from tara_events.outbox import record_event

from .models import OutboxEvent

PRODUCER = "ads-service"


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
            # The edge's request id, for admin's audit log (None outside requests).
            correlation_id=current_request_id(),
        ),
    )
