"""Profile & Pages domain models (owns `profile_db`).

References to accounts are bare UUIDs (the Identity context owns accounts); there
are no cross-database foreign keys. Block visibility is kept as a local
read-model fed by `user.blocked` / `user.unblocked` events.
"""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent
from tara_resilience.idempotency import AbstractIdempotencyRecord


class Visibility(models.TextChoices):
    PUBLIC = "public", "Public"
    FRIENDS = "friends_only", "Friends only"
    PRIVATE = "private", "Private"
    CUSTOM = "custom", "Custom"  # custom audiences: placeholder for a later phase


# Profile fields whose visibility can be configured independently.
CONTROLLABLE_FIELDS = ["bio", "intro", "city", "country", "links", "education", "work"]


class UserProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_id = models.UUIDField(unique=True)  # -> Identity account
    handle = models.CharField(max_length=30, unique=True)  # stored lowercase
    display_name = models.CharField(max_length=80, blank=True, default="")
    bio = models.CharField(max_length=300, blank=True, default="")
    intro = models.TextField(blank=True, default="")
    city = models.CharField(max_length=80, blank=True, default="")
    country = models.CharField(max_length=80, blank=True, default="")
    avatar_media_id = models.UUIDField(null=True, blank=True)
    cover_media_id = models.UUIDField(null=True, blank=True)
    visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.PUBLIC
    )
    completion_pct = models.PositiveSmallIntegerField(default=0)
    # Discoverability (roadmap 1.6, 05 decision 9): ``False`` keeps the account
    # out of people search and suggestions. Carried in ``profile.updated``;
    # friends and followers still reach the profile as before.
    searchable = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "user_profile"
        indexes = [models.Index(fields=["account_id"], name="profile_account_idx")]

    def __str__(self) -> str:
        return f"@{self.handle}"


class ProfileFieldPrivacy(models.Model):
    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="field_privacy")
    field_key = models.CharField(max_length=40)
    visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.PUBLIC
    )

    class Meta:
        db_table = "profile_field_privacy"
        constraints = [
            models.UniqueConstraint(fields=["profile", "field_key"], name="field_privacy_uniq"),
        ]


class UserLink(models.Model):
    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="links")
    label = models.CharField(max_length=60)
    url = models.URLField(max_length=300)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "user_link"
        ordering = ["position"]


class UserEducation(models.Model):
    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="education")
    school = models.CharField(max_length=120)
    degree = models.CharField(max_length=120, blank=True, default="")
    field = models.CharField(max_length=120, blank=True, default="")
    start_year = models.PositiveSmallIntegerField(null=True, blank=True)
    end_year = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        db_table = "user_education"


class UserWorkExperience(models.Model):
    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="work")
    company = models.CharField(max_length=120)
    title = models.CharField(max_length=120, blank=True, default="")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)

    class Meta:
        db_table = "user_work_experience"


class PageRole(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    EDITOR = "editor", "Editor"
    MODERATOR = "moderator", "Moderator"
    ADVERTISER = "advertiser", "Advertiser"
    ANALYST = "analyst", "Analyst"


class Page(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        SUSPENDED = "suspended", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    owner_account_id = models.UUIDField()
    handle = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=80, blank=True, default="")
    description = models.TextField(blank=True, default="")
    avatar_media_id = models.UUIDField(null=True, blank=True)
    cover_media_id = models.UUIDField(null=True, blank=True)
    contact = models.JSONField(default=dict, blank=True)
    location = models.CharField(max_length=160, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PUBLISHED)
    created_by = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "page"

    def __str__(self) -> str:
        return self.name


class PageMember(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="members")
    account_id = models.UUIDField()
    role = models.CharField(max_length=16, choices=PageRole.choices, default=PageRole.EDITOR)
    invited_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "page_member"
        constraints = [
            models.UniqueConstraint(fields=["page", "account_id"], name="page_member_uniq"),
        ]


class BlockedPair(models.Model):
    """Local read-model of blocks (fed by user.blocked/unblocked) for visibility.

    Stored directionally: a row (blocker, blocked) means blocker blocked blocked.
    """

    blocker_id = models.UUIDField()
    blocked_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "blocked_pair"
        constraints = [
            models.UniqueConstraint(fields=["blocker_id", "blocked_id"], name="blocked_pair_uniq"),
        ]
        indexes = [models.Index(fields=["blocked_id"], name="blocked_blocked_idx")]


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
