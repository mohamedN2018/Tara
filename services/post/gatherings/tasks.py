from __future__ import annotations

from celery import shared_task

from . import services


@shared_task(name="gatherings.tick", ignore_result=True)
def tick() -> dict:
    """Every few minutes: send the reminders whose window opened (once each),
    then store ``ended`` on events that are over."""
    return {"reminders": services.send_due_reminders(), "ended": services.mark_ended()}
