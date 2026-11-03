"""Admin domain models (owns `admin_db`): flags, config, audit, health, statistics."""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent


class FeatureFlag(models.Model):
    key = models.CharField(max_length=80, primary_key=True)
    enabled = models.BooleanField(default=False)
    rollout_pct = models.PositiveSmallIntegerField(default=0)  # 0..100
    targeting = models.JSONField(default=dict, blank=True)
    description = models.CharField(max_length=300, blank=True, default="")
    updated_by = models.UUIDField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "feature_flag"


class SystemConfig(models.Model):
    key = models.CharField(max_length=120, primary_key=True)
    value = models.JSONField(default=dict, blank=True)
    updated_by = models.UUIDField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "system_config"


class AuditLog(models.Model):
    """Legacy admin-only audit rows (before 8.1). No longer written: migration
    0003 copied them into ``AuditEntry``. Kept so the migration stays additive."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    actor_id = models.UUIDField()
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=120, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_log"


class ServiceHealthSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    service = models.CharField(max_length=40)
    status = models.CharField(max_length=12)  # ready | not_ready | unreachable
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "service_health_snapshot"
        indexes = [models.Index(fields=["service", "-checked_at"], name="health_service_idx")]


class AuditEntry(models.Model):
    """One staff or system decision, from any service (roadmap 8.1).

    Most rows come from admin's event consumer (role grants, capability matrix
    changes, moderation actions, appeal resolutions, ad reviews); admin writes
    its own decisions (feature flags, audit exports) in the request transaction.
    ``detail`` holds ids and enums only, never message text or private content.
    ``request_id`` is the edge's id for the request that made the decision.
    """

    class ActorKind(models.TextChoices):
        ACCOUNT = "account", "Account"
        SYSTEM = "system", "System"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    actor_kind = models.CharField(max_length=8, choices=ActorKind.choices)
    actor_id = models.UUIDField(null=True, blank=True)
    # The producing service for a system actor (an expiry job has no account).
    actor_name = models.CharField(max_length=64, blank=True, default="")
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=32, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    request_id = models.CharField(max_length=100, blank=True, default="")
    detail = models.JSONField(default=dict, blank=True)
    # The event this row came from: a redelivery cannot add a second row.
    source_event_id = models.UUIDField(null=True, blank=True, unique=True)

    class Meta:
        db_table = "audit_entry"
        indexes = [
            # Index set after QTech core.AuditLog: newest first, by actor, by
            # action, by target. Each ends with the keyset order.
            models.Index(fields=["-occurred_at", "-id"], name="audit_entry_time_idx"),
            models.Index(fields=["actor_id", "-occurred_at"], name="audit_entry_actor_idx"),
            models.Index(fields=["action", "-occurred_at"], name="audit_entry_action_idx"),
            models.Index(
                fields=["target_type", "target_id", "-occurred_at"], name="audit_entry_target_idx"
            ),
        ]


class PlatformStat(models.Model):
    """Latest value of one platform counter, polled from its owning service (8.11)."""

    metric = models.CharField(max_length=40, primary_key=True)
    service = models.CharField(max_length=40)
    value = models.BigIntegerField(null=True, blank=True)
    # Last successful poll; ``checked_at`` is the last attempt.
    updated_at = models.DateTimeField(null=True, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "platform_stat"


class OutboxEvent(AbstractOutboxEvent):
    class Meta(AbstractOutboxEvent.Meta):
        abstract = False  # inheriting an abstract Meta re-inherits abstract=True
        db_table = "outbox_event"


class ProcessedEvent(AbstractProcessedEvent):
    class Meta(AbstractProcessedEvent.Meta):
        abstract = False  # inheriting an abstract Meta re-inherits abstract=True
        db_table = "processed_event"
