"""Search's beat tasks (search-worker)."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="searchsvc.warm_signal_optins", ignore_result=True)
def warm_signal_optins() -> int:
    """Re-warm the search-signal opt-in cache from its table (WP 8.7-B2)."""
    from . import signals

    return signals.warm()
