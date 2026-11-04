"""Moderation domain models (owns `moderation_db`)."""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent


class Report(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    reporter_id = models.UUIDField()
    target_type = models.CharField(
        max_length=20
    )  # post | comment | message | listing | page | user
    target_id = models.CharField(max_length=64)
    reason = models.CharField(max_length=200, blank=True, default="")
    # What the reporter saw, when the target is private to its context (a chat
    # message): text only, as the owning service sent it (decision 5.13).
    evidence = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "report"
        indexes = [models.Index(fields=["target_type", "target_id"], name="report_target_idx")]


class ModerationCase(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Open"
        IN_REVIEW = "in_review", "In review"
        RESOLVED = "resolved", "Resolved"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    target_type = models.CharField(max_length=20)
    target_id = models.CharField(max_length=64)
    severity = models.CharField(max_length=12, default="normal")
    state = models.CharField(max_length=12, choices=State.choices, default=State.OPEN)
    report_count = models.PositiveIntegerField(default=0)
    assigned_to = models.UUIDField(null=True, blank=True)
    # Who the reported content belongs to: the only account that may appeal.
    # Null for cases opened by events that predate it, which nobody can appeal.
    owner_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "moderation_case"
        constraints = [
            models.UniqueConstraint(
                fields=["target_type", "target_id"],
                condition=models.Q(state__in=["open", "in_review"]),
                name="one_open_case_per_target",
            ),
        ]
        indexes = [models.Index(fields=["state", "-created_at"], name="case_queue_idx")]


class ModerationAction(models.Model):
    class Action(models.TextChoices):
        REMOVE = "remove", "Remove content"
        RESTRICT = "restrict", "Restrict user"
        WARN = "warn", "Warn"
        SHADOW = "shadow", "Shadow restrict"
        DISMISS = "dismiss", "Dismiss"
        APPROVE = "approve", "Approve"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    case = models.ForeignKey(ModerationCase, on_delete=models.CASCADE, related_name="actions")
    moderator_id = models.UUIDField()
    action = models.CharField(max_length=12, choices=Action.choices)
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "moderation_action"


class Appeal(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        UPHELD = "upheld", "Upheld"
        OVERTURNED = "overturned", "Overturned"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    case = models.ForeignKey(ModerationCase, on_delete=models.CASCADE, related_name="appeals")
    account_id = models.UUIDField()
    text = models.TextField(blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "appeal"


class ContentPolicy(models.Model):
    key = models.CharField(max_length=60, unique=True)
    version = models.PositiveIntegerField(default=1)
    body = models.TextField(blank=True, default="")
    effective_from = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "content_policy"


class ModerationAuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    case = models.ForeignKey(ModerationCase, on_delete=models.CASCADE, related_name="audit")
    actor_id = models.UUIDField()
    action = models.CharField(max_length=40)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "moderation_audit_log"


class OutboxEvent(AbstractOutboxEvent):
    class Meta(AbstractOutboxEvent.Meta):
        abstract = False
        db_table = "outbox_event"


class ProcessedEvent(AbstractProcessedEvent):
    class Meta(AbstractProcessedEvent.Meta):
        abstract = False
        db_table = "processed_event"
