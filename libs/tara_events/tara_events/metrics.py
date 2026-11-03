"""Outbox backlog gauge, computed from the database on each /metrics scrape."""

from __future__ import annotations

from django.apps import apps
from django.conf import settings


def install_outbox_gauge() -> None:
    """Call from ``AppConfig.ready()``. A no-op for services without an outbox."""
    model_path = getattr(settings, "TARA_OUTBOX_MODEL", None)
    if not model_path:
        return
    from tara_observability.metrics import OUTBOX_PENDING

    def pending() -> int:
        return apps.get_model(model_path).objects.filter(published_at__isnull=True).count()

    OUTBOX_PENDING.labels(service=settings.SERVICE_NAME).set_function(pending)
