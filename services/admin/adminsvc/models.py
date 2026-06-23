"""Admin domain models (owns `admin_db`): flags, config, roles, audit, health."""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7


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


class AccountRole(models.Model):
    """Role registry. Identity reads this to embed `roles` into access tokens."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_id = models.UUIDField()
    role = models.CharField(max_length=32)  # admin | moderator | analyst | advertiser ...
    granted_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "account_role"
        constraints = [
            models.UniqueConstraint(fields=["account_id", "role"], name="account_role_uniq"),
        ]
        indexes = [models.Index(fields=["account_id"], name="account_role_acct_idx")]


class AuditLog(models.Model):
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
