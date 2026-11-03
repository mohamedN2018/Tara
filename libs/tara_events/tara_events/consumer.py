"""Consumer-side idempotency guard.

Wrap event handling so re-delivery (at-least-once) is a no-op. Each service
passes its concrete ProcessedEvent model.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from django.db import transaction

if TYPE_CHECKING:
    from .models import AbstractProcessedEvent


@contextmanager
def idempotent(processed_model: type[AbstractProcessedEvent], event_id: str, consumer: str):
    """Yield True the first time (event_id, consumer) is seen, else skip the block.

    Usage:
        with idempotent(ProcessedEvent, env.event_id, "feed") as fresh:
            if fresh:
                handle(env)
    """
    with transaction.atomic():
        _, created = processed_model.objects.get_or_create(event_id=event_id, consumer=consumer)
        yield created
