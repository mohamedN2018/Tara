"""Abstract outbox + idempotency models.

These are ``abstract = True`` so each service defines a CONCRETE table it owns
(migrations live in the service, not in this shared lib). This keeps the
database-per-service rule intact while sharing the schema definition.
"""

from __future__ import annotations

from django.db import models

from .envelope import uuid7


class AbstractOutboxEvent(models.Model):
    """Staged event written in the SAME transaction as the business change.

    A relay (Celery task) drains unpublished rows to the broker. At-least-once
    delivery; consumers dedupe on ``event_id``.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    event_type = models.CharField(max_length=120)
    event_version = models.PositiveIntegerField(default=1)
    payload = models.JSONField()  # the full envelope dict
    partition_key = models.CharField(max_length=200, blank=True, default="")
    correlation_id = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        abstract = True
        indexes = [
            # The relay's hot query: oldest unpublished first.
            models.Index(
                fields=["created_at"],
                name="%(class)s_unpub_idx",
                condition=models.Q(published_at__isnull=True),
            ),
        ]
        ordering = ["created_at"]


class AbstractProcessedEvent(models.Model):
    """Consumer-side idempotency ledger: an event handled once stays handled.

    Keyed by (event_id, consumer) so the same event may be processed once per
    distinct handler within this service, but never twice by the same handler.
    """

    event_id = models.UUIDField()
    consumer = models.CharField(max_length=120)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "consumer"], name="%(class)s_event_consumer_uniq"
            ),
        ]
