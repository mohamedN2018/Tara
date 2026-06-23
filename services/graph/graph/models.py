"""Social Graph domain models (owns `graph_db`).

Relationships reference accounts by bare UUID. DB constraints enforce the
invariants (no duplicate friendship/follow/block, symmetric friendship stored
once with low<high) so concurrent/idempotent requests cannot create duplicates.
"""

from __future__ import annotations

from django.db import models
from django.db.models import F, Q

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent
from tara_resilience.idempotency import AbstractIdempotencyRecord


class AccountRef(models.Model):
    """Minimal read-model of known accounts (fed by account.registered).

    Lets the graph validate that a follow/friend target actually exists without
    a synchronous call to Identity.
    """

    account_id = models.UUIDField(primary_key=True)
    handle = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "account_ref"


class Friendship(models.Model):
    """A symmetric friendship, stored once with account_low_id < account_high_id."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_low_id = models.UUIDField()
    account_high_id = models.UUIDField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    requested_by = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "friendship"
        constraints = [
            models.UniqueConstraint(
                fields=["account_low_id", "account_high_id"], name="friendship_pair_uniq"
            ),
            models.CheckConstraint(
                check=Q(account_low_id__lt=F("account_high_id")), name="friendship_low_lt_high"
            ),
        ]
        indexes = [models.Index(fields=["account_high_id", "status"], name="friendship_high_idx")]


class FollowRelation(models.Model):
    class TargetType(models.TextChoices):
        USER = "user", "User"
        PAGE = "page", "Page"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    follower_id = models.UUIDField()
    target_id = models.UUIDField()
    target_type = models.CharField(
        max_length=8, choices=TargetType.choices, default=TargetType.USER
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "follow_relation"
        constraints = [
            models.UniqueConstraint(
                fields=["follower_id", "target_id", "target_type"], name="follow_uniq"
            ),
        ]
        indexes = [models.Index(fields=["target_id", "target_type"], name="follow_target_idx")]


class BlockRelation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    blocker_id = models.UUIDField()
    blocked_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "block_relation"
        constraints = [
            models.UniqueConstraint(fields=["blocker_id", "blocked_id"], name="block_uniq"),
        ]
        indexes = [models.Index(fields=["blocked_id"], name="block_blocked_idx")]


class CloseFriendRelation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_id = models.UUIDField()
    friend_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "close_friend_relation"
        constraints = [
            models.UniqueConstraint(fields=["account_id", "friend_id"], name="close_friend_uniq"),
        ]


# ---- platform tables ----
class OutboxEvent(AbstractOutboxEvent):
    class Meta(AbstractOutboxEvent.Meta):
        abstract = False
        db_table = "outbox_event"


class ProcessedEvent(AbstractProcessedEvent):
    class Meta(AbstractProcessedEvent.Meta):
        abstract = False
        db_table = "processed_event"


class IdempotencyRecord(AbstractIdempotencyRecord):
    class Meta(AbstractIdempotencyRecord.Meta):
        abstract = False
        db_table = "idempotency_record"
