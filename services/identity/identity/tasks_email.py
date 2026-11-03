"""Mail delivery runs on a worker so an SMTP outage is retried, not lost."""

from __future__ import annotations

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail


@shared_task(
    name="identity.send_email",
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=1800,
    retry_jitter=True,
    max_retries=8,
    ignore_result=True,
)
def send_email(to: str, subject: str, body: str) -> None:
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
