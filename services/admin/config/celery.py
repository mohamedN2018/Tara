from __future__ import annotations

import os

from celery import Celery
from celery.signals import beat_init

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("admin")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.autodiscover_tasks(["tara_events"], related_name="tasks")


@beat_init.connect
def _poll_once_at_start(sender=None, **kwargs) -> None:
    """Interval entries first fire one interval after beat starts: after a deploy
    the monitor would show no statistics for five minutes. Poll once now."""
    app.send_task("adminsvc.poll_service_health")
    app.send_task("adminsvc.poll_platform_stats")
