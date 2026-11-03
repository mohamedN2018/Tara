"""Notification creation + read/preferences logic."""

from __future__ import annotations

import hashlib
import logging

from django.db import transaction
from django.utils import timezone

from . import events, push, tasks
from .models import Notification, NotificationPreference, PushDeviceToken

logger = logging.getLogger("tara.notification.services")


def _queue_push(notification_id: str) -> None:
    try:
        tasks.deliver_push.delay(notification_id)
    except Exception:  # noqa: BLE001 - the in-app notification is already saved
        logger.warning("could not queue web push", exc_info=True)


def notify(
    recipient_id: str,
    kind: str,
    *,
    actor_id: str | None = None,
    subject_ref: str = "",
    group_key: str = "",
    body: str = "",
) -> Notification | None:
    """Create an in-app notification (unless self-directed or muted) and announce it."""
    if actor_id and str(actor_id) == str(recipient_id):
        return None  # never notify yourself
    pref = NotificationPreference.objects.filter(account_id=recipient_id).first()
    if pref and not pref.channel_enabled(kind, "in_app", default=True):
        return None

    with transaction.atomic():
        notification = Notification.objects.create(
            recipient_id=recipient_id,
            kind=kind,
            actor_id=actor_id,
            subject_ref=subject_ref,
            group_key=group_key,
            body=body,
        )
        events.emit(
            "notification.created",
            subject_id=str(notification.id),
            payload={
                "recipient": str(recipient_id),
                "kind": kind,
                "notification_id": str(notification.id),
                "actor": str(actor_id) if actor_id else None,
            },
            partition_key=f"recipient:{recipient_id}",
        )
        notification_id = str(notification.id)
        transaction.on_commit(lambda: _queue_push(notification_id))
    return notification


def list_for(recipient_id: str, *, unread_only: bool = False):
    qs = Notification.objects.filter(recipient_id=recipient_id)
    if unread_only:
        qs = qs.filter(read_at__isnull=True)
    return qs.order_by("-created_at")


def unread_count(recipient_id: str) -> int:
    return Notification.objects.filter(recipient_id=recipient_id, read_at__isnull=True).count()


def mark_read(recipient_id: str, *, ids: list[str] | None = None, mark_all: bool = False) -> int:
    qs = Notification.objects.filter(recipient_id=recipient_id, read_at__isnull=True)
    if not mark_all:
        qs = qs.filter(id__in=ids or [])
    return qs.update(read_at=timezone.now())


def register_push_token(account_id: str, platform: str, token: str):
    obj, _ = PushDeviceToken.objects.update_or_create(
        token=token, defaults={"account_id": account_id, "platform": platform}
    )
    return obj


def endpoint_token(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


def register_web_push(account_id: str, subscription: dict) -> PushDeviceToken:
    with transaction.atomic():
        obj, _ = PushDeviceToken.objects.update_or_create(
            token=endpoint_token(subscription["endpoint"]),
            defaults={"account_id": account_id, "platform": "web", "subscription": subscription},
        )
        stale = (
            PushDeviceToken.objects.filter(account_id=account_id, platform="web")
            .order_by("-last_seen_at")
            .values_list("pk", flat=True)[push.MAX_SUBSCRIPTIONS_PER_ACCOUNT :]
        )
        PushDeviceToken.objects.filter(pk__in=list(stale)).delete()
    return obj


def unregister_web_push(account_id: str, endpoint: str) -> None:
    PushDeviceToken.objects.filter(
        account_id=account_id, token=endpoint_token(endpoint), platform="web"
    ).delete()


def get_or_create_preferences(account_id: str) -> NotificationPreference:
    pref, _ = NotificationPreference.objects.get_or_create(account_id=account_id)
    return pref
