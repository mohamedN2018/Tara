"""Celery app for the Identity service.

Runs the outbox relay on a beat schedule and any future async identity tasks
(e.g. email sending). Broker = RabbitMQ (ADR-003).
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("identity")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Make the shared outbox relay task discoverable by this worker.
app.autodiscover_tasks(["tara_events"], related_name="tasks")
