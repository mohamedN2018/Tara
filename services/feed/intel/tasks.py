"""Tara Intelligence background tasks (run by feed's Celery worker with beat)."""

from __future__ import annotations

import logging

from celery import shared_task

from .signals import partitions

logger = logging.getLogger("tara.intel.tasks")


@shared_task(name="intel.maintain_partitions", ignore_result=True)
def maintain_partitions() -> dict:
    """Partitions 7 days ahead; drop the ones past retention (WP 2.2)."""
    made = partitions.make_partitions()
    dropped = partitions.drop_expired()
    if dropped:
        logger.info("intel partitions dropped", extra={"dropped": dropped})
    return {"ensured": len(made), "dropped": dropped}


@shared_task(name="intel.purge_signal_batches", ignore_result=True)
def purge_signal_batches() -> int:
    """Batch dedupe rows older than 48 h."""
    return partitions.purge_batches()


@shared_task(name="intel.rebuild_pools", ignore_result=True)
def rebuild_pools(force: bool = False) -> dict | None:
    """The Home discovery pools (WP 4b.6). Beat ticks every minute; a rebuild runs only
    when ``pools.rebuild_s`` of the active home version has passed, and never under a
    version without pools (``home@1``, ``home@2``)."""
    from . import config, discovery

    cfg = config.for_surface("home")
    if not discovery.has_pools(cfg):
        return None
    if not force and not discovery.due(cfg):
        return {"due": False}
    return discovery.rebuild(cfg)


@shared_task(name="intel.purge_feed_sessions", ignore_result=True)
def purge_feed_sessions() -> int:
    """Visit rows past ``session.feed_session_retention_d`` (R3 WP 4b.4; nightly)."""
    from . import config, session_ctx

    return session_ctx.purge(config.for_surface("home"))


@shared_task(name="intel.aggregate_engagement", ignore_result=True)
def aggregate_engagement() -> dict:
    """The engagement aggregator v0 (R3 WP 4b.13): every 60 s, idempotent."""
    from .signals import aggregate

    return aggregate.run()


@shared_task(name="intel.reset_recommendations", ignore_result=True)
def reset_recommendations(account_id: str, reset_at: str) -> dict:
    """R4 WP 8.4-B2: the deletions of "Reset recommendations", off the request path."""
    from datetime import datetime

    from . import preferences

    return preferences.run_reset(account_id, datetime.fromisoformat(reset_at))


@shared_task(name="intel.rebuild_creator_quality", ignore_result=True)
def rebuild_creator_quality() -> dict:
    """R4 WP 6.3: ``intel_creator_quality``, nightly."""
    from . import creator_quality

    return creator_quality.rebuild()


@shared_task(name="intel.purge_preference_logs", ignore_result=True)
def purge_preference_logs() -> dict:
    """R4: preference changes after 180 d, feedback after 365 d, debug consent after
    90 d (``retention`` block of the Home config), nightly."""
    from . import config, retention

    return retention.purge(config.for_surface("home"))
