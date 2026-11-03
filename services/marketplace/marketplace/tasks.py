"""Celery tasks for the Marketplace service (run by the beat in marketplace-relay)."""

from __future__ import annotations

from celery import shared_task

from . import view_counter


@shared_task(name="marketplace.flush_view_counts", ignore_result=True)
def flush_view_counts() -> int:
    return view_counter.flush()
