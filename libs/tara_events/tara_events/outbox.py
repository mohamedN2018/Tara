"""Outbox write + relay.

`record_event` is called INSIDE the business transaction (so the event row
commits atomically with the state change). `publish_pending` is the relay that a
Celery task runs to drain unpublished rows to the broker.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import connection, transaction
from django.utils import timezone

from .envelope import EventEnvelope
from .publisher import EventPublisher, PublisherUnavailable, get_publisher

if TYPE_CHECKING:
    from .models import AbstractOutboxEvent

logger = logging.getLogger("tara.events.outbox")

MAX_ATTEMPTS = 8


def record_event(outbox_model: type[AbstractOutboxEvent], envelope: EventEnvelope):
    """Persist an event to the outbox, inside the caller's transaction."""
    if not connection.in_atomic_block:
        raise RuntimeError("record_event must run inside a transaction.")
    return outbox_model.objects.create(
        id=envelope.event_id,
        event_type=envelope.event_type,
        event_version=envelope.event_version,
        payload=envelope.to_dict(),
        partition_key=envelope.partition_key or "",
        correlation_id=envelope.correlation_id or "",
    )


def publish_pending(
    outbox_model: type[AbstractOutboxEvent],
    *,
    publisher: EventPublisher | None = None,
    batch_size: int = 200,
) -> int:
    """Publish unpublished outbox rows in creation order. Returns count published.

    Each row is locked (``select_for_update(skip_locked)``) so multiple relay
    workers can run concurrently without double-publishing. Failures increment
    ``attempts`` and are retried next pass until MAX_ATTEMPTS, then parked. A
    broker outage stops the pass without counting against any row.
    """
    publisher = publisher or get_publisher()
    published = 0

    with transaction.atomic():
        rows = list(
            outbox_model.objects.select_for_update(skip_locked=True)
            .filter(published_at__isnull=True, attempts__lt=MAX_ATTEMPTS)
            .order_by("created_at")[:batch_size]
        )
        for row in rows:
            try:
                publisher.publish(EventEnvelope.from_dict(row.payload))
            except PublisherUnavailable:
                # A broker outage is not the event's fault: try again next pass.
                logger.warning("broker unavailable; outbox relay paused")
                break
            except Exception as exc:  # noqa: BLE001 - record & continue; relay retries
                row.attempts += 1
                row.last_error = str(exc)[:1000]
                row.save(update_fields=["attempts", "last_error"])
                logger.warning(
                    "outbox publish failed",
                    extra={"event_id": str(row.id), "attempt": row.attempts},
                )
                continue
            row.published_at = timezone.now()
            row.save(update_fields=["published_at"])
            published += 1

    if published:
        logger.info("outbox published batch", extra={"count": published})
    return published
