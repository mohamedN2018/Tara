"""Notification domain models (owns `notif_db`)."""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    recipient_id = models.UUIDField()
    kind = models.CharField(max_length=40)
    actor_id = models.UUIDField(null=True, blank=True)
    subject_ref = models.CharField(max_length=120, blank=True, default="")  # e.g. "post:<id>"
    group_key = models.CharField(max_length=120, blank=True, default="")
    body = models.CharField(max_length=300, blank=True, default="")
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification"
        indexes = [models.Index(fields=["recipient_id", "-created_at"], name="notif_recipient_idx")]


class NotificationPreference(models.Model):
    account_id = models.UUIDField(primary_key=True)
    # Per-kind channel toggles, e.g. {"post.reaction": {"in_app": true, "push": false}}.
    prefs = models.JSONField(default=dict, blank=True)
    quiet_hours = models.JSONField(default=dict, blank=True)  # {"start": "22:00", "end": "07:00"}
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notification_preference"

    def channel_enabled(self, kind: str, channel: str, default: bool = True) -> bool:
        return self.prefs.get(kind, {}).get(channel, default)


class PushDeviceToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_id = models.UUIDField()
    platform = models.CharField(max_length=12)  # ios | android | web
    token = models.CharField(max_length=400, unique=True)
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
