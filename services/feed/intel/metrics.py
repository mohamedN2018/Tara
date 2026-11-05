"""Prometheus counters for telemetry ingestion and eligibility (scraped from feed and
feed-signals)."""

from __future__ import annotations

try:
    from prometheus_client import Counter

    SIGNALS_ACCEPTED = Counter(
        "intel_signal_accepted_total", "Telemetry events stored.", ["origin"]
    )
    SIGNALS_REJECTED = Counter(
        "intel_signal_rejected_total", "Telemetry events dropped, by reason.", ["reason"]
    )
    ELIGIBILITY_DROPS = Counter(
        "intel_eligibility_drop_total",
        "Candidates removed by an eligibility rule (02 section 11), by rule.",
        ["rule"],
    )
    SUSPECT_ENGAGEMENT = Counter(
        "intel_suspect_engagement_total",
        "Reactions excluded from rates as suspect (02 section 16), by reason.",
        ["reason"],
    )
except ImportError:  # pragma: no cover - metrics are optional
    SIGNALS_ACCEPTED = SIGNALS_REJECTED = ELIGIBILITY_DROPS = SUSPECT_ENGAGEMENT = None


def accepted(origin: str, n: int) -> None:
    if SIGNALS_ACCEPTED is not None and n:
        SIGNALS_ACCEPTED.labels(origin=str(origin)).inc(n)


def rejected(reason: str, n: int = 1) -> None:
    if SIGNALS_REJECTED is not None and n:
        SIGNALS_REJECTED.labels(reason=reason).inc(n)


def eligibility_dropped(rule: str, n: int = 1) -> None:
    if ELIGIBILITY_DROPS is not None and n:
        ELIGIBILITY_DROPS.labels(rule=rule).inc(n)


def suspect_engagement(reason: str, n: int = 1) -> None:
    if SUSPECT_ENGAGEMENT is not None and n:
        SUSPECT_ENGAGEMENT.labels(reason=reason).inc(n)
