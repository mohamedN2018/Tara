"""Notification creation, aggregation, read state, cleanup and preferences."""

from __future__ import annotations

import hashlib
import logging

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from . import events, push, registry, tasks
from .models import (
    Notification,
    NotificationActor,
    NotificationPreference,
    PushDeviceToken,
)

logger = logging.getLogger("tara.notification.services")

MAX_RECENT_ACTORS = 3
MAX_READ_IDS = 100
_AGGREGATE_ATTEMPTS = 3


def _queue_push(notification_id: str) -> None:
    try:
        tasks.deliver_push.delay(notification_id)
    except Exception:  # noqa: BLE001 - the in-app notification is already saved
        logger.warning("could not queue web push", exc_info=True)


def _announce(notification: Notification) -> None:
    """``notification.created`` carries ids only; clients fetch the row by id.

    It is also sent when an event merges into an open aggregate, so open lists
    move the row to the top with its new count.
    """
    events.emit(
        "notification.created",
        subject_id=str(notification.id),
        payload={
            "recipient": str(notification.recipient_id),
            "kind": notification.kind,
            "notification_id": str(notification.id),
            "actor": str(notification.actor_id) if notification.actor_id else None,
        },
        partition_key=f"recipient:{notification.recipient_id}",
    )


def _emit_read(recipient_id: str, ids: list[str] | None, *, all_read: bool = False) -> None:
    """Tell the recipient's other tabs and devices (the realtime frame is a follow-up)."""
    events.emit(
        "notification.read",
        subject_id=str(recipient_id),
        payload={
            "recipient": str(recipient_id),
            "notification_ids": [] if all_read else [str(i) for i in (ids or [])][:MAX_READ_IDS],
            "all": all_read,
        },
        partition_key=f"recipient:{recipient_id}",
    )


def _emit_deleted(recipient_id: str, ids: list[str]) -> None:
    events.emit(
        "notification.deleted",
        subject_id=str(recipient_id),
        payload={"recipient": str(recipient_id), "notification_ids": [str(i) for i in ids]},
        partition_key=f"recipient:{recipient_id}",
    )


def _merge(row: Notification, *, actor_id, fields: dict, now) -> None:
    """Fold one more event into a locked, open aggregate."""
    if actor_id:
        actor, created = NotificationActor.objects.get_or_create(
            notification=row, actor_id=actor_id, defaults={"last_at": now}
        )
        if created:
            row.actor_count += 1  # only a new person changes the count
        else:
            actor.last_at = now
            actor.save(update_fields=["last_at"])
        recent = [str(actor_id)] + [a for a in row.recent_actor_ids if a != str(actor_id)]
        row.recent_actor_ids = recent[:MAX_RECENT_ACTORS]
        row.actor_id = actor_id
    if "message_id" in fields.get("data", {}):
        # How many messages the row stands for, so deleting the latest knows
        # whether anything is left to show (``forget_message``).
        fields = {**fields, "data": {**fields["data"], "message_count": _message_count(row) + 1}}
    for name, value in fields.items():
        setattr(row, name, value)
    row.last_event_at = now
    row.save()


def _upsert_aggregate(
    recipient_id: str, key: str, *, actor_id, fields: dict, window, now
) -> tuple[Notification, bool]:
    """Merge into the open row for ``key``, or insert one. Returns ``(row, inserted)``.

    Concurrency: the open row is locked with ``select_for_update``. When there is
    none, two consumers can both try to insert; the partial unique index lets one
    win, the other gets ``IntegrityError`` inside its savepoint and loops to lock
    and merge the winner's row.

    Window: an open row whose first event is older than ``window`` is closed in
    the same locked step (its key gets a per-row suffix) before the new row is
    inserted, so the unique index never rejects the next event.
    """
    for _ in range(_AGGREGATE_ATTEMPTS):
        row = (
            Notification.objects.select_for_update()
            .filter(recipient_id=recipient_id, aggregate_key=key, read_at__isnull=True)
            .first()
        )
        if row is not None and row.created_at < now - window:
            row.aggregate_key = registry.closed_key(key, row.id)
            row.save(update_fields=["aggregate_key"])
            row = None
        if row is not None:
            _merge(row, actor_id=actor_id, fields=fields, now=now)
            return row, False
        try:
            with transaction.atomic():
                row = Notification.objects.create(
                    recipient_id=recipient_id,
                    aggregate_key=key,
                    actor_id=actor_id,
                    actor_count=1 if actor_id else 0,
                    recent_actor_ids=[str(actor_id)] if actor_id else [],
                    last_event_at=now,
                    **fields,
                )
                if actor_id:
                    NotificationActor.objects.create(
                        notification=row, actor_id=actor_id, last_at=now
                    )
            return row, True
        except IntegrityError:
            continue  # a concurrent insert holds the key now: lock it and merge
    raise RuntimeError(f"could not aggregate notification {key!r}")


def notify(
    recipient_id: str,
    kind: str,
    *,
    actor_id: str | None = None,
    subject_ref: str = "",
    target_ref: str = "",
    group_key: str = "",
    body: str = "",
    data: dict | None = None,
) -> Notification | None:
    """Record one event for ``recipient_id`` and announce it.

    In-app and push are decided separately (the user's choice for the kind, then
    for its category, then the registry default). Push only: a hidden,
    already-read row carries the push. Neither: nothing is stored. Aggregated
    kinds merge into the open row for their key.
    """
    if not recipient_id or (actor_id and str(actor_id) == str(recipient_id)):
        return None  # never notify yourself
    pref = NotificationPreference.objects.filter(account_id=recipient_id).first()
    prefs = pref.prefs if pref else {}
    in_app = registry.channel_enabled(prefs, kind, "in_app")
    wants_push = registry.channel_enabled(prefs, kind, "push")
    if not in_app and not wants_push:
        return None

    spec = registry.get(kind)
    now = timezone.now()
    fields = {
        "kind": kind,
        "category": spec.category,
        "subject_ref": subject_ref[:120],
        "target_ref": target_ref[:120],
        "group_key": group_key[:120],
        "body": body[:300],
        "data": registry.clean_data(data),
    }
    key = registry.aggregate_key(kind, subject_ref) if in_app else ""

    with transaction.atomic():
        if key:
            notification, inserted = _upsert_aggregate(
                recipient_id, key, actor_id=actor_id, fields=fields, window=spec.window, now=now
            )
        else:
            notification = Notification.objects.create(
                recipient_id=recipient_id,
                actor_id=actor_id,
                actor_count=1 if actor_id else 0,
                recent_actor_ids=[str(actor_id)] if actor_id else [],
                visible_in_app=in_app,
                read_at=None if in_app else now,
                last_event_at=now,
                **fields,
            )
            if actor_id:
                NotificationActor.objects.create(
                    notification=notification, actor_id=actor_id, last_at=now
                )
            inserted = True
        if in_app:
            _announce(notification)
        if wants_push and (inserted or spec.push_on_merge):
            notification_id = str(notification.id)
            transaction.on_commit(lambda: _queue_push(notification_id))
    return notification


# ---- reading ----------------------------------------------------------------------


def visible_for(recipient_id: str):
    return Notification.objects.filter(recipient_id=recipient_id, visible_in_app=True)


def list_for(recipient_id: str, *, unread_only: bool = False, category: str = "", kind: str = ""):
    qs = visible_for(recipient_id)
    if unread_only:
        qs = qs.filter(read_at__isnull=True)
    if category:
        qs = qs.filter(category=category)
    if kind:
        qs = qs.filter(kind=kind)
    return qs.order_by("-last_event_at", "-id")


def get_for(recipient_id: str, notification_id: str) -> Notification | None:
    return visible_for(recipient_id).filter(id=notification_id).first()


def unread_count(recipient_id: str) -> int:
    return visible_for(recipient_id).filter(read_at__isnull=True).count()


@transaction.atomic
def mark_read(recipient_id: str, *, ids: list[str] | None = None, mark_all: bool = False) -> int:
    qs = Notification.objects.filter(recipient_id=recipient_id, read_at__isnull=True)
    if not mark_all:
        ids = [str(i) for i in (ids or [])][:MAX_READ_IDS]
        qs = qs.filter(id__in=ids)
    count = qs.update(read_at=timezone.now())
    if count:
        _emit_read(recipient_id, ids, all_read=mark_all)
    return count


@transaction.atomic
def delete(recipient_id: str, notification_id: str) -> bool:
    deleted, _ = Notification.objects.filter(recipient_id=recipient_id, id=notification_id).delete()
    if deleted:
        _emit_deleted(recipient_id, [str(notification_id)])
    return bool(deleted)


@transaction.atomic
def resolve(recipient_id: str, notification_id: str, resolution: str) -> Notification | None:
    """Record the outcome of an inline action and mark the row read. Idempotent.

    Raises ``ValueError`` for a resolution the kind does not allow.
    """
    notification = (
        Notification.objects.select_for_update()
        .filter(recipient_id=recipient_id, id=notification_id, visible_in_app=True)
        .first()
    )
    if notification is None:
        return None
    if resolution not in registry.get(notification.kind).resolutions:
        raise ValueError(resolution)
    update = ["resolution"]
    notification.resolution = resolution
    was_unread = notification.read_at is None
    if was_unread:
        notification.read_at = timezone.now()
        update.append("read_at")
    notification.save(update_fields=update)
    if was_unread:
        _emit_read(recipient_id, [str(notification_id)])
    return notification


# ---- event-driven resolution and cleanup ------------------------------------------


@transaction.atomic
def resolve_friend_request(request_id: str, resolution: str) -> int:
    """The graph request changed state: settle its notification without the client."""
    rows = list(
        Notification.objects.select_for_update().filter(
            kind="friend.request", data__request_id=str(request_id)
        )
    )
    now = timezone.now()
    for row in rows:
        update = ["resolution"]
        row.resolution = resolution
        if row.read_at is None:
            row.read_at = now
            update.append("read_at")
            _emit_read(str(row.recipient_id), [str(row.id)])
        row.save(update_fields=update)
    return len(rows)


def clear_conversation(reader_id: str, conversation_id: str) -> int:
    """``message.read``: reading the chat clears its message notification."""
    ids = list(
        Notification.objects.filter(
            recipient_id=reader_id,
            kind="message",
            subject_ref=f"conversation:{conversation_id}",
            read_at__isnull=True,
        ).values_list("id", flat=True)
    )
    return mark_read(reader_id, ids=[str(i) for i in ids]) if ids else 0


def _delete_rows(qs) -> int:
    by_recipient: dict[str, list[str]] = {}
    for nid, recipient in qs.values_list("id", "recipient_id"):
        by_recipient.setdefault(str(recipient), []).append(str(nid))
    if not by_recipient:
        return 0
    Notification.objects.filter(id__in=[i for ids in by_recipient.values() for i in ids]).delete()
    for recipient, ids in by_recipient.items():
        _emit_deleted(recipient, ids)
    return sum(len(ids) for ids in by_recipient.values())


@transaction.atomic
def purge_subject(ref: str) -> int:
    """A post (or other subject) is gone: its notifications go too, for every recipient."""
    if not ref or ref.endswith(":"):
        return 0
    return _delete_rows(Notification.objects.filter(Q(subject_ref=ref) | Q(target_ref=ref)))


@transaction.atomic
def purge_comments(comment_ids: list[str]) -> int:
    """Comments are gone: drop the replies and mentions they caused.

    An aggregate (``post.comment``) that points at one of them is dropped when
    that comment's author was its only actor; one counting other people stays.
    """
    refs = [f"comment:{c}" for c in comment_ids if c]
    if not refs:
        return 0
    aggregated = [k.name for k in registry.KINDS.values() if k.aggregate]
    about = Notification.objects.filter(target_ref__in=refs)
    return _delete_rows(
        about.exclude(kind__in=aggregated) | about.filter(kind__in=aggregated, actor_count__lte=1)
    )


def _message_count(row: Notification) -> int:
    return int((row.data or {}).get("message_count") or 1)


@transaction.atomic
def forget_message(conversation_id: str, message_id: str, *, deleted: bool) -> int:
    """A message was deleted (for everyone, or by moderation) or edited.

    A row whose latest message it was loses that message's preview; deleted,
    and the only message the row stood for, the row goes (``notification.deleted``).
    Rows from before rows recorded their message are blanked, since their
    source is unknown. Idempotent. Returns the number of rows changed.
    """
    rows = Notification.objects.filter(
        kind__in=("message", "message.page", "message.support"),
        subject_ref=f"conversation:{conversation_id}",
    )
    latest = rows.filter(data__message_id=str(message_id))
    removed = 0
    if deleted:
        only = [r.id for r in latest.select_for_update() if _message_count(r) <= 1]
        removed = _delete_rows(Notification.objects.filter(id__in=only))
    blanked = (
        rows.exclude(body="")
        .filter(Q(data__message_id=str(message_id)) | ~Q(data__has_key="message_id"))
        .update(body="")
    )
    return removed + blanked


@transaction.atomic
def remove_actor(recipient_id: str, actor_id: str) -> int:
    """``recipient`` and ``actor`` are now blocked: drop that person from the rows.

    An aggregate keeps its other actors with an exact count; a row left without
    anyone is deleted.
    """
    changed = 0
    emptied: list[str] = []
    # (notification, actor) is unique, so the subquery yields each row once.
    rows = Notification.objects.select_for_update().filter(
        recipient_id=recipient_id,
        id__in=NotificationActor.objects.filter(actor_id=actor_id).values("notification_id"),
    )
    for row in rows:
        NotificationActor.objects.filter(notification=row, actor_id=actor_id).delete()
        remaining = list(
            NotificationActor.objects.filter(notification=row)
            .order_by("-last_at")
            .values_list("actor_id", flat=True)
        )
        if not remaining:
            emptied.append(str(row.id))
            continue
        row.actor_count = len(remaining)
        row.recent_actor_ids = [str(a) for a in remaining[:MAX_RECENT_ACTORS]]
        row.actor_id = remaining[0]
        row.save(update_fields=["actor_count", "recent_actor_ids", "actor_id"])
        changed += 1
    # Rows written before the actor table existed have no NotificationActor rows.
    legacy = Notification.objects.filter(recipient_id=recipient_id, actor_id=actor_id)
    changed += _delete_rows(
        Notification.objects.filter(Q(id__in=emptied) | Q(id__in=legacy.values("id")))
    )
    return changed


# ---- devices ----------------------------------------------------------------------


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


# ---- preferences ------------------------------------------------------------------


def get_or_create_preferences(account_id: str) -> NotificationPreference:
    pref, _ = NotificationPreference.objects.get_or_create(account_id=account_id)
    return pref


@transaction.atomic
def update_preferences(account_id: str, changes: dict) -> NotificationPreference:
    """Merge, never replace: a client that sends one toggle keeps all the others."""
    pref, _ = NotificationPreference.objects.select_for_update().get_or_create(
        account_id=account_id
    )
    if "prefs" in changes:
        merged = {k: dict(v) for k, v in (pref.prefs or {}).items() if isinstance(v, dict)}
        for key, channels in changes["prefs"].items():
            current = merged.setdefault(key, {})
            for channel, value in channels.items():
                if value is None:
                    current.pop(channel, None)
                else:
                    current[channel] = value
            if not current:
                merged.pop(key)
        pref.prefs = merged
    if "quiet_hours" in changes:
        pref.quiet_hours = changes["quiet_hours"]
    if "message_previews" in changes:
        pref.message_previews = changes["message_previews"]
    pref.save()
    return pref
