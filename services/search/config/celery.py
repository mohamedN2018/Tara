from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# The outbox relay (search.queried) and the opt-in cache warm-up (WP 8.7-B2).
app = Celery("search")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.autodiscover_tasks(["tara_events"], related_name="tasks")
