"""Web Push delivery (VAPID), with keys from the environment.

Without keys this is a no-op with a log line. Subscription endpoints come from
browsers, so only known push services are accepted (``is_allowed_endpoint``):
otherwise the server could be made to POST to any address.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from pywebpush import WebPushException, webpush

from . import registry
from .models import Notification, NotificationDeliveryLog, NotificationPreference, PushDeviceToken

logger = logging.getLogger("tara.notification.push")

TTL_SECONDS = 24 * 60 * 60
GONE_STATUSES = {404, 410}  # The browser dropped this subscription.
MAX_SUBSCRIPTIONS_PER_ACCOUNT = 10


class RetryablePushError(Exception):
    """The push service had a temporary failure."""


def configured() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def is_allowed_endpoint(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or parts.username or parts.password:
        return False
    if parts.port not in (None, 443) or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(
        host == allowed.removeprefix("*.") or host.endswith(allowed.removeprefix("*"))
        if allowed.startswith("*.")
        else host == allowed
        for allowed in settings.WEB_PUSH_ALLOWED_HOSTS
    )


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def in_quiet_hours(quiet: dict | None, now: datetime | None = None) -> bool:
    """Whether ``now`` falls in the window, which may cross midnight."""
    if not quiet or not quiet.get("start") or not quiet.get("end"):
        return False
    now = now or timezone.now()
    try:
        local = now.astimezone(ZoneInfo(quiet.get("timezone") or "UTC"))
    except (KeyError, ValueError):
        local = now.astimezone(UTC)
    current = _minutes(time.strftime(local.timetz(), "%H:%M"))
    start, end = _minutes(quiet["start"]), _minutes(quiet["end"])
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _log(notification: Notification, status: str, error: str = "", attempts: int = 1) -> None:
    NotificationDeliveryLog.objects.create(
        notification=notification,
        channel="push",
        status=status,
        attempts=attempts,
        last_error=error[:1000],
    )


def _payload(notification: Notification, pref: NotificationPreference | None = None) -> str:
    """What the service worker shows: ids, a count and a same-origin path. A
    message's text is included only while the user allows message previews."""
    previews = pref.message_previews if pref else True
    body = notification.body if notification.kind != "message" or previews else ""
    return json.dumps(
        {
            "kind": notification.kind,
            "notification_id": str(notification.id),
            "body": body,
            "count": notification.actor_count,
            "url": registry.url_for(notification),
            # A browser replaces a notification with the same tag instead of stacking it.
            "tag": notification.aggregate_key.split("~", 1)[0]
            or notification.group_key
            or str(notification.id),
        }
    )


def _send(token: PushDeviceToken, data: str) -> bool:
    """True if the push service took it; False if the subscription is gone."""
    try:
        webpush(
            subscription_info=token.subscription,
            data=data,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            ttl=TTL_SECONDS,
            timeout=10,
        )
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in GONE_STATUSES:
            token.delete()
            logger.info("dropped expired push subscription")
            return False
        if status is None or status >= 500 or status == 429:
            raise RetryablePushError(str(exc)) from exc
        raise
    return True


def deliver(notification_id: str) -> str:
    """Send one notification to the recipient's browsers. Returns what happened."""
    if not configured():
        logger.info("web push skipped: VAPID keys are not set")
        return "disabled"
    notification = Notification.objects.filter(id=notification_id).first()
    if notification is None:
        return "missing"
    tokens = list(
        PushDeviceToken.objects.filter(
            account_id=notification.recipient_id, platform="web", subscription__isnull=False
        )
    )
    if not tokens:
        return "no_subscribers"
    pref = NotificationPreference.objects.filter(account_id=notification.recipient_id).first()
    if not registry.channel_enabled(pref.prefs if pref else {}, notification.kind, "push"):
        _log(notification, "muted")
        return "muted"
    if pref and in_quiet_hours(pref.quiet_hours):
        _log(notification, "quiet")
        return "quiet"

    data = _payload(notification, pref)
    failures: list[str] = []
    delivered = 0
    # One bad subscription retries the task; the shared `tag` makes a browser
    # replace, not repeat, a notification it already showed.
    retry: RetryablePushError | None = None
    for token in tokens:
        try:
            delivered += _send(token, data)
        except RetryablePushError as exc:
            retry = exc
        except WebPushException as exc:
            failures.append(str(exc))
    if retry is not None:
        raise retry
    if failures:
        _log(notification, "failed", "; ".join(failures))
        return "failed"
    status = "sent" if delivered else "expired"
    _log(notification, status)
    return status
