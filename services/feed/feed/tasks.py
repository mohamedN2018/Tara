"""Feed's background tasks (run by ``feed-relay``'s Celery worker)."""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction

from . import readmodels

logger = logging.getLogger("tara.feed.tasks")


@shared_task(name="feed.refresh_post_score", ignore_result=True)
def refresh_post_score(post_id: str) -> None:
    """Copy a post's engagement onto its feed rows, outside the request that changed it."""
    readmodels.refresh_score(post_id)


def refresh_score_after_commit(post_id) -> None:
    """Queue ``refresh_post_score`` once the caller's transaction commits.

    The ranking reads ``PostStats`` itself, so a lost refresh only leaves the
    stored ``FeedItem.score`` stale until the post's next engagement event.
    """

    def _queue() -> None:
        try:
            refresh_post_score.delay(str(post_id))
        except Exception:  # noqa: BLE001 - a broker hiccup must not fail a committed hide
            logger.warning("score refresh not queued", extra={"post_id": str(post_id)})

    transaction.on_commit(_queue)
