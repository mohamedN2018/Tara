"""Shared Celery task that drains a service's outbox.

A service wires this up by:
  1. setting ``TARA_OUTBOX_MODEL = "identity.OutboxEvent"`` in settings,
  2. registering ``tara_events.tasks.publish_outbox`` on a Celery beat schedule
     (e.g. every 2 seconds).

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
