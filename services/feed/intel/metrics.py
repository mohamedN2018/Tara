"""Prometheus counters for telemetry ingestion and eligibility (scraped from feed and
feed-signals)."""

from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram

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
    # 07 WP 4b.0, 4b.6 and 4b.11.
    HOT_WRITE_FAILED = Counter(
        "intel_hot_write_failed_total",
        "redis-hot writes refused (noeviction OOM) or failed, by key family.",
        ["key"],
    )
    FIRST_PAGE_OVERLAP = Histogram(
        "intel_first_page_overlap",
        "Jaccard of a Home first page against the viewer's previous one (feed:head).",
        buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.99, 1.0),
    )
    REPEAT_DISPLAY = Counter(
        "intel_repeat_display_total",
        "Items of a Home first page that were already on the viewer's previous one.",
    )
    CAUGHT_UP = Counter(
        "intel_caught_up_total",
        "Ranked Home pages on which the viewer's connection inventory ran out.",
    )
    RANK_SESSION_OOM = Counter(
        "intel_rank_session_oom_total",
        "Ranked first pages whose session redis-hot refused (noeviction OOM, 08 7.3).",
    )
    RANK_SESSION_LOST = Counter(
        "intel_rank_session_lost_total",
        "Ranked later pages that found no session (missing, or replaced by another tab).",
        ["reason"],
    )
    VISITS = Counter(
        "intel_feed_visit_total", "Home first pages by visit kind (06 section 4.2).", ["kind"]
    )
    POOL_REBUILDS = Counter(
        "intel_pool_rebuild_total", "Discovery pool rebuilds, by outcome.", ["outcome"]
    )
except ImportError:  # pragma: no cover - metrics are optional
    SIGNALS_ACCEPTED = SIGNALS_REJECTED = ELIGIBILITY_DROPS = SUSPECT_ENGAGEMENT = None
    HOT_WRITE_FAILED = FIRST_PAGE_OVERLAP = REPEAT_DISPLAY = CAUGHT_UP = POOL_REBUILDS = None
    RANK_SESSION_OOM = RANK_SESSION_LOST = VISITS = None


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


def hot_write_failed(key: str) -> None:
    if HOT_WRITE_FAILED is not None:
        HOT_WRITE_FAILED.labels(key=key).inc()


def first_page_overlap(value: float) -> None:
    if FIRST_PAGE_OVERLAP is not None:
        FIRST_PAGE_OVERLAP.observe(value)


def repeat_display(n: int) -> None:
    if REPEAT_DISPLAY is not None and n:
        REPEAT_DISPLAY.inc(n)


def caught_up() -> None:
    if CAUGHT_UP is not None:
        CAUGHT_UP.inc()


def rank_session_oom() -> None:
    if RANK_SESSION_OOM is not None:
        RANK_SESSION_OOM.inc()


def rank_session_lost(reason: str) -> None:
    if RANK_SESSION_LOST is not None:
        RANK_SESSION_LOST.labels(reason=reason).inc()


def visit(kind: str) -> None:
    if VISITS is not None:
        VISITS.labels(kind=kind).inc()


def pool_rebuilt(outcome: str) -> None:
    if POOL_REBUILDS is not None:
        POOL_REBUILDS.labels(outcome=outcome).inc()


class HotMemoryCollector:
    """``intel_redis_hot_used_ratio``: redis-hot ``used_memory / maxmemory``, read at
    scrape time (one ``INFO memory``; no sample while redis-hot is unreachable)."""

    def collect(self):
        from prometheus_client.core import GaugeMetricFamily

        from . import hot

        family = GaugeMetricFamily(
            "intel_redis_hot_used_ratio", "redis-hot used_memory / maxmemory (alert > 0.8)."
        )
        ratio = hot.used_ratio()
        if ratio is not None:
            family.add_metric([], ratio)
        yield family


_collector_registered = False


def register_collectors() -> None:
    global _collector_registered
    if _collector_registered:
        return
    try:
        from prometheus_client import REGISTRY
    except ImportError:  # pragma: no cover
        return
    try:
        REGISTRY.register(HotMemoryCollector())
    except ValueError:  # already registered (a reloaded app registry)
        pass
    _collector_registered = True
