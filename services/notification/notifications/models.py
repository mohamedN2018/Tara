"""Notification domain models (owns `notif_db`)."""

from __future__ import annotations

from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent


class Notification(models.Model):
    """One row the recipient sees, possibly standing for many events (an aggregate).

    An aggregate stays *open* while it is unread and holds ``aggregate_key``; the
    partial unique index ``notif_open_aggregate_uniq`` keeps one open row per key.
    Reading it (or the window expiring, see ``services.notify``) closes it.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    recipient_id = models.UUIDField()
    kind = models.CharField(max_length=40)
    category = models.CharField(max_length=24, blank=True, default="")
    # The most recent actor; every distinct actor is in NotificationActor.
    actor_id = models.UUIDField(null=True, blank=True)
    subject_ref = models.CharField(max_length=120, blank=True, default="")  # e.g. "post:<id>"
    target_ref = models.CharField(max_length=120, blank=True, default="")  # e.g. "comment:<id>"
    group_key = models.CharField(max_length=120, blank=True, default="")
    aggregate_key = models.CharField(max_length=200, blank=True, default="")
    body = models.CharField(max_length=300, blank=True, default="")
    # Whitelisted ids and short codes for the client (registry.clean_data); never on the bus.
    data = models.JSONField(default=dict, blank=True)
    actor_count = models.PositiveIntegerField(default=0)
    recent_actor_ids = models.JSONField(default=list, blank=True)  # newest first, at most 3
    # Hidden rows exist only to carry a push the user wants without an in-app
    # entry. They are created read, so they never hold an aggregate open.
    visible_in_app = models.BooleanField(default=True, db_default=True)
    resolution = models.CharField(max_length=16, blank=True, default="")
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_event_at = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "notification"
        indexes = [
            models.Index(fields=["recipient_id", "-created_at"], name="notif_recipient_idx"),
            models.Index(
                fields=["recipient_id", "-last_event_at", "-id"], name="notif_recipient_recent_idx"
            ),
            models.Index(
                fields=["recipient_id", "category"],
                name="notif_unread_idx",
                condition=models.Q(read_at__isnull=True, visible_in_app=True),
            ),
            models.Index(fields=["subject_ref"], name="notif_subject_idx"),
            models.Index(fields=["target_ref"], name="notif_target_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient_id", "aggregate_key"],
                name="notif_open_aggregate_uniq",
                condition=models.Q(read_at__isnull=True) & ~models.Q(aggregate_key=""),
            )
        ]


class NotificationActor(models.Model):
    """Each distinct actor of a notification: exact counts, and block cleanup per actor."""

    id = models.BigAutoField(primary_key=True)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="actors")
    actor_id = models.UUIDField()
    last_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "notification_actor"
        constraints = [
            models.UniqueConstraint(fields=["notification", "actor_id"], name="notif_actor_uniq")
        ]
        indexes = [models.Index(fields=["actor_id"], name="notif_actor_idx")]


class NotificationPreference(models.Model):
    account_id = models.UUIDField(primary_key=True)
    # Channel toggles per kind or per category, e.g. {"post.reaction": {"push": false},
    # "social": {"in_app": true}}. Validated against the registry; PATCH merges.
    prefs = models.JSONField(default=dict, blank=True)
    quiet_hours = models.JSONField(default=dict, blank=True)  # {"start": "22:00", "end": "07:00"}
    # Off: message pushes say "new message" instead of showing the text.
    message_previews = models.BooleanField(default=True, db_default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notification_preference"

    def channel_enabled(self, kind: str, channel: str) -> bool:
        from . import registry

        return registry.channel_enabled(self.prefs, kind, channel)


class PushDeviceToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_id = models.UUIDField()
    platform = models.CharField(max_length=12)  # ios | android | web
    # Web: a hash of the endpoint, which has no length limit. Others: the device token.
    token = models.CharField(max_length=400, unique=True)
    subscription = models.JSONField(null=True, blank=True)  # web: endpoint + keys
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "push_device_token"
        indexes = [models.Index(fields=["account_id"], name="push_account_idx")]


class NotificationDeliveryLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries"
    )
    channel = models.CharField(max_length=12)  # in_app | push | email
    status = models.CharField(max_length=12, default="queued")
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_delivery_log"


class OutboxEvent(AbstractOutboxEvent):
    class Meta(AbstractOutboxEvent.Meta):
        abstract = False
        db_table = "outbox_event"


class ProcessedEvent(AbstractProcessedEvent):
    class Meta(AbstractProcessedEvent.Meta):
        abstract = False
        db_table = "processed_event"
