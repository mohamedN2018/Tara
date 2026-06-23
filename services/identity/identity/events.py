"""Helpers to emit security events and domain events from the Identity service.

Domain events go through the OUTBOX (recorded in the same DB transaction as the
state change), never published inline. See docs/04-event-contracts.md.
"""

from __future__ import annotations

from typing import Any

from tara_events.envelope import EventEnvelope
from tara_events.outbox import record_event

from .models import Account, OutboxEvent, SecurityEvent

PRODUCER = "identity-service"


def emit_security_event(
    account: Account | None,
    event_type: str,
    metadata: dict[str, Any] | None = None,
    *,
    ip_region: str = "",
) -> None:
    SecurityEvent.objects.create(
        account=account,
        type=event_type,
        ip_region=ip_region,
        metadata=metadata or {},
    )


def emit_domain_event(
    event_type: str,
    *,
    subject_id: str,
    payload: dict[str, Any],
    actor_id: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Record a domain event to the outbox (call inside a transaction)."""
    envelope = EventEnvelope(
        event_type=event_type,
        payload=payload,
        subject_id=str(subject_id),
        producer=PRODUCER,
        actor_id=str(actor_id) if actor_id else None,
        correlation_id=correlation_id,
    )
    record_event(OutboxEvent, envelope)
