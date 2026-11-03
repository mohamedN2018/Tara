from __future__ import annotations

from celery import shared_task

from . import push


@shared_task(
    name="notifications.deliver_push",
    ignore_result=True,
    autoretry_for=(push.RetryablePushError,),
    retry_backoff=30,
    max_retries=3,
)
def deliver_push(notification_id: str) -> str:
    return push.deliver(notification_id)


@shared_task(
    name="notifications.deliver_call_push",
    ignore_result=True,
    autoretry_for=(push.RetryablePushError,),
    retry_backoff=2,  # a ring is only useful for seconds
    max_retries=2,
)
def deliver_call_push(recipient_id: str, data: dict) -> str:
    return push.deliver_call(recipient_id, data)
