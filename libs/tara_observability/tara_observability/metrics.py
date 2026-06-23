"""Prometheus metrics helpers.

Services expose ``/metrics`` via django-prometheus (added to each service's
requirements + middleware). This module holds shared custom metrics so every
service reports the same names (RED-style + outbox lag).
"""

from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, Histogram

    EVENTS_PUBLISHED = Counter(
        "tara_events_published_total",
        "Domain events published from the outbox.",
        ["event_type", "service"],
    )
    OUTBOX_PENDING = Gauge(
        "tara_outbox_pending",
        "Outbox rows awaiting publication.",
        ["service"],
    )
    DEPENDENCY_LATENCY = Histogram(
        "tara_dependency_latency_seconds",
        "Latency of synchronous calls to other services.",
        ["dependency", "service"],
    )
    _AVAILABLE = True
except ImportError:  # pragma: no cover - metrics optional at import time
    EVENTS_PUBLISHED = OUTBOX_PENDING = DEPENDENCY_LATENCY = None
    _AVAILABLE = False


def metrics_available() -> bool:
    return _AVAILABLE
