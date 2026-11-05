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
