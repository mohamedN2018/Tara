"""Shared Celery task that drains a service's outbox.

A service wires this up by:
  1. setting ``TARA_OUTBOX_MODEL = "identity.OutboxEvent"`` in settings,
  2. registering ``tara_events.publish_outbox`` on a Celery beat schedule
     (e.g. every 2 seconds), and ``tara_events.purge_events`` (e.g. hourly).

Kept transport-agnostic: it resolves the concrete outbox model from settings.
"""

from __future__ import annotations

from celery import shared_task
from django.apps import apps
from django.conf import settings


def _resolve_outbox_model():
    dotted = getattr(settings, "TARA_OUTBOX_MODEL", None)
    if not dotted:
        raise RuntimeError("TARA_OUTBOX_MODEL is not configured for this service.")
    app_label, model_name = dotted.split(".")
    return apps.get_model(app_label, model_name)


@shared_task(name="tara_events.publish_outbox", ignore_result=True)
def publish_outbox(batch_size: int = 200) -> int:
    from .outbox import publish_pending

    model = _resolve_outbox_model()
    return publish_pending(model, batch_size=batch_size)


def _resolve_processed_model():
    """The service's ``ProcessedEvent``, next to its outbox. Producer-only services have none."""
    try:
        return apps.get_model(_resolve_outbox_model()._meta.app_label, "ProcessedEvent")
    except LookupError:
        return None


@shared_task(name="tara_events.purge_events", ignore_result=True)
def purge_events(retention_days: int = 7) -> dict[str, int]:
    from .outbox import purge_old_events

    return purge_old_events(
        _resolve_outbox_model(), _resolve_processed_model(), retention_days=retention_days
    )
