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
    # Profile's discoverability flag (``UserProfile.searchable``, carried in
    # ``profile.updated``). ``False`` keeps the account out of suggestions.
    searchable = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Lifecycle (intelligence WP 3.3, D5): ``account.deactivated`` /
    # ``reactivated`` and ``account.suspended`` / ``unsuspended`` set the two
    # flags independently (newest event wins per flag); ``active`` is
    # ``not (deactivated or suspended)``, kept in the row so readers filter on
    # one column. An inactive account is left out of suggestions and fan-out.
    deactivated = models.BooleanField(default=False, db_default=False)
    deactivated_event_at = models.DateTimeField(null=True, blank=True)
    suspended = models.BooleanField(default=False, db_default=False)
    suspended_event_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True, db_default=True)
    # Account moderation (rule E11, D14): ``moderation.actioned`` with
    # target_type=user and ``restrict`` / ``shadow`` sets it, ``reinstate``
    # clears it (the timestamp stays so an older redelivery cannot re-apply
    # it). Sensitive: a shadow is never shown to anyone, the account included.
    # A restricted account keeps its fan-out; it only leaves suggestions.
    restriction = models.CharField(max_length=8, blank=True, default="", db_default="")
    restriction_case_id = models.UUIDField(null=True, blank=True)
    restriction_event_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "account_ref"


class ListVisibility(models.TextChoices):
    PUBLIC = "public", "Public"
    FRIENDS = "friends", "Friends"
    ONLY_ME = "only_me", "Only me"


class RelationshipSettings(models.Model):
    """Who may see an account's relationship lists and counts (roadmap 1.6).

    A missing row means every default: lists and counts are public and anyone
    may send a friend request.
    """

    class RequestsFrom(models.TextChoices):
        EVERYONE = "everyone", "Everyone"
        FRIENDS_OF_FRIENDS = "friends_of_friends", "Friends of friends"

    account_id = models.UUIDField(primary_key=True)
    friends_list_visibility = models.CharField(
        max_length=12, choices=ListVisibility.choices, default=ListVisibility.PUBLIC
    )
    follow_lists_visibility = models.CharField(
        max_length=12, choices=ListVisibility.choices, default=ListVisibility.PUBLIC
    )
    counts_visibility = models.CharField(
        max_length=12, choices=ListVisibility.choices, default=ListVisibility.PUBLIC
    )
    friend_requests_from = models.CharField(
        max_length=20, choices=RequestsFrom.choices, default=RequestsFrom.EVERYONE
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "relationship_settings"


class PageRef(models.Model):
    """Read model of pages (fed by ``page.created``/``page.updated``) for the
    "Suggested pages" widget. Only newer events are applied."""

    page_id = models.UUIDField(primary_key=True)
    handle = models.CharField(max_length=64, blank=True, default="")
    name = models.CharField(max_length=160, blank=True, default="")
    category = models.CharField(max_length=80, blank=True, default="")
    owner_id = models.UUIDField(null=True, blank=True)
    avatar_media_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(max_length=16, blank=True, default="")
    deleted = models.BooleanField(default=False)
    source_occurred_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "page_ref"
        indexes = [models.Index(fields=["status", "deleted"], name="page_ref_live_idx")]


class _OwnedEdge(models.Model):
    """A one-way, owner-private relation from ``account_id`` to ``target_id``."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_id = models.UUIDField()
    target_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class MuteRelation(_OwnedEdge):
    """``account_id`` no longer sees ``target_id``'s posts in their feed. The
    muted account is never told."""

    class Meta:
        db_table = "mute_relation"
        constraints = [
            models.UniqueConstraint(fields=["account_id", "target_id"], name="mute_uniq")
        ]


class RestrictRelation(_OwnedEdge):
    """``target_id``'s comments on ``account_id``'s posts are visible only to
    the two of them."""

    class Meta:
        db_table = "restrict_relation"
        constraints = [
            models.UniqueConstraint(fields=["account_id", "target_id"], name="restrict_uniq")
        ]


class FavoriteRelation(_OwnedEdge):
    """``target_id``'s posts come first in ``account_id``'s feed."""

    class Meta:
        db_table = "favorite_relation"
        constraints = [
            models.UniqueConstraint(fields=["account_id", "target_id"], name="favorite_uniq")
        ]


class DismissedSuggestion(models.Model):
    class TargetType(models.TextChoices):
        USER = "user", "User"
        PAGE = "page", "Page"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_id = models.UUIDField()
    target_id = models.UUIDField()
    target_type = models.CharField(max_length=8, choices=TargetType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dismissed_suggestion"
        constraints = [
            models.UniqueConstraint(
                fields=["account_id", "target_id", "target_type"], name="dismissed_uniq"
            )
        ]


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
