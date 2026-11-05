"""Prometheus counters for telemetry ingestion (scraped from feed and feed-signals)."""

from __future__ import annotations

try:
    from prometheus_client import Counter

    SIGNALS_ACCEPTED = Counter(
        "intel_signal_accepted_total", "Telemetry events stored.", ["origin"]
    )
    SIGNALS_REJECTED = Counter(
        "intel_signal_rejected_total", "Telemetry events dropped, by reason.", ["reason"]
    )
except ImportError:  # pragma: no cover - metrics are optional
    SIGNALS_ACCEPTED = SIGNALS_REJECTED = None


def accepted(origin: str, n: int) -> None:
    if SIGNALS_ACCEPTED is not None and n:
        SIGNALS_ACCEPTED.labels(origin=str(origin)).inc(n)


def rejected(reason: str, n: int = 1) -> None:
    if SIGNALS_REJECTED is not None and n:
        SIGNALS_REJECTED.labels(reason=reason).inc(n)
