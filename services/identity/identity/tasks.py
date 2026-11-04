"""Periodic identity jobs (found by Celery's autodiscovery of ``tasks``)."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="identity.lift_expired_suspensions", ignore_result=True)
def lift_expired_suspensions() -> int:
    """Lift suspensions whose end date has passed (roadmap 8.4); sign-in also checks."""
    from .account_admin import lift_expired_suspensions as lift

    return lift()


@shared_task(name="identity.purge_scheduled_deletions", ignore_result=True)
def purge_scheduled_deletions() -> int:
    """Erase accounts whose 30-day deletion grace ended (3C); emits account.deleted."""
    from .account_center import purge_due_deletions

    return purge_due_deletions()
