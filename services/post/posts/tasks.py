from __future__ import annotations

import logging

from celery import shared_task
from celery.signals import worker_ready

from . import composer

logger = logging.getLogger("tara.post.tasks")


@shared_task(name="posts.publish_scheduled", ignore_result=True)
def publish_scheduled() -> int:
    """Every minute (beat): publish the scheduled posts whose time has come."""
    return composer.publish_due()


@worker_ready.connect
def catch_up_on_boot(sender=None, **_kwargs) -> None:
    """A worker that starts publishes what came due while nothing was running,
    without waiting for the first beat tick. SKIP LOCKED keeps it safe beside
    other workers doing the same."""
    try:
        published = composer.publish_due()
        if published:
            logger.info("published scheduled posts on boot", extra={"count": published})
    except Exception:  # noqa: BLE001 - the beat task retries within a minute
        logger.warning("scheduled-post catch-up on boot failed", exc_info=True)
