from __future__ import annotations

from celery import shared_task

from . import reconcile as reconcile_job


@shared_task(name="reels.reconcile", ignore_result=True)
def reconcile() -> dict:
    """Every 15 minutes (beat): repair reels whose video was deleted, failed or
    left unbound in media (``reels.reconcile``)."""
    return reconcile_job.reconcile()
