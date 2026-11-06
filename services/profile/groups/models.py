"""Groups in ``profile_db``: the group, memberships with roles, rules, reports.

Accounts and media are bare UUIDs (services own their data). Group posts and
group events live in the post service, which keeps a read model of these rows
fed by ``group.*`` events.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from tara_events.envelope import uuid7

MAX_NAME = 100
MAX_DESCRIPTION = 5000
MAX_RULES = 10
MAX_RULE_TITLE = 100
MAX_RULE_BODY = 600


class Privacy(models.TextChoices):
    PUBLIC = "public", "Public: anyone sees the group and its content"
    PRIVATE = "private", "Private: anyone finds it, only members see content"
    HIDDEN = "hidden", "Hidden: only members find it"


class Category(models.TextChoices):
    GENERAL = "general", "General"
    EDUCATION = "education", "Education"
    BUSINESS = "business", "Business"
    TECHNOLOGY = "technology", "Technology"
    SPORTS = "sports", "Sports"
    GAMING = "gaming", "Gaming"
    ARTS = "arts", "Arts"
    ENTERTAINMENT = "entertainment", "Entertainment"
    HEALTH = "health", "Health"
    TRAVEL = "travel", "Travel"
    FOOD = "food", "Food"
    PARENTING = "parenting", "Parenting"
    RELIGION = "religion", "Religion"
    LOCAL = "local", "Local community"
    BUY_SELL = "buy_sell", "Buy and sell"
    HOBBIES = "hobbies", "Hobbies"
    SCIENCE = "science", "Science"
    OTHER = "other", "Other"


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MODERATOR = "moderator", "Moderator"
    MEMBER = "member", "Member"


class State(models.TextChoices):
    REQUESTED = "requested", "Asked to join"
    INVITED = "invited", "Invited"
    ACTIVE = "active", "Member"
    BANNED = "banned", "Banned"


class Group(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Removed by moderation"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    handle = models.CharField(max_length=30, unique=True)  # lowercase, immutable
    name = models.CharField(max_length=MAX_NAME)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.GENERAL)
    cover_media_id = models.UUIDField(null=True, blank=True)
    privacy = models.CharField(max_length=8, choices=Privacy.choices, default=Privacy.PUBLIC)
    membership_approval = models.BooleanField(default=False)
    post_approval = models.BooleanField(default=False)
    member_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "social_group"
        indexes = [
            models.Index(fields=["privacy", "status"], name="group_privacy_status_idx"),
            models.Index(fields=["category", "-member_count"], name="group_category_idx"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_live(self) -> bool:
        """Deleted and moderator-removed groups are hidden from everyone."""
        return self.deleted_at is None and self.status == self.Status.ACTIVE


class GroupMember(models.Model):
    """One row per (group, account) relation. No row means no relation: leaving,
    a removal, a declined request and an unban all delete the row."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="members")
    account_id = models.UUIDField()
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    state = models.CharField(max_length=10, choices=State.choices)
    invited_by = models.UUIDField(null=True, blank=True)
    # Opt-in per group: "tell me about new posts" (off by default).
    notify_posts = models.BooleanField(default=False)
    joined_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "group_member"
        constraints = [
            models.UniqueConstraint(fields=["group", "account_id"], name="group_member_uniq"),
            # Staff roles only on active members; requests and bans are plain members.
            models.CheckConstraint(
                condition=Q(role="member") | Q(state="active"),
                name="group_member_staff_active",
            ),
        ]
        indexes = [
            models.Index(fields=["account_id", "state"], name="group_member_account_idx"),
            models.Index(fields=["group", "state", "role"], name="group_member_state_idx"),
        ]


class GroupRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="rules")
    title = models.CharField(max_length=MAX_RULE_TITLE)
    body = models.TextField(blank=True, default="")
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "group_rule"
        ordering = ["position", "created_at"]


class ReportReason(models.TextChoices):
    """An enum, so ``group.reported`` carries no free text."""

    SPAM = "spam", "Spam"
    SCAM = "scam", "Scam or fraud"
    HATE = "hate", "Hate speech"
    VIOLENCE = "violence", "Violence"
    NUDITY = "nudity", "Nudity"
    HARASSMENT = "harassment", "Harassment"
    FALSE_INFORMATION = "false_information", "False information"
    OTHER = "other", "Something else"


class GroupReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="reports")
    reporter_id = models.UUIDField()
    reason = models.CharField(max_length=20, choices=ReportReason.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "group_report"
        constraints = [
            models.UniqueConstraint(fields=["group", "reporter_id"], name="group_report_uniq"),
        ]


class GroupSuggestionDismissal(models.Model):
    """ "Not interested": the group is never suggested to this account again."""

    id = models.BigAutoField(primary_key=True)
    account_id = models.UUIDField()
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "group_suggestion_dismissal"
        constraints = [
            models.UniqueConstraint(
                fields=["account_id", "group"], name="group_suggestion_dismissal_uniq"
            ),
        ]


# ---- Tara Intelligence read models (R4, WP 5.5) ----
class IntelConfig(models.Model):
    """The last published config of a surface (``intel.config.published``)."""

    surface = models.CharField(max_length=20, primary_key=True)
    version = models.PositiveIntegerField()
    params = models.JSONField(default=dict)
    experiment = models.JSONField(null=True, blank=True)
    published_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "intel_config"


class IntelExposureSeen(models.Model):
    """One row per (account, experiment) once its exposure was emitted."""

    id = models.BigAutoField(primary_key=True)
    account_id = models.UUIDField()
    experiment_key = models.CharField(max_length=60)
    variant = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "intel_exposure_seen"
        constraints = [
            models.UniqueConstraint(
                fields=["account_id", "experiment_key"], name="intel_exposure_seen_uniq"
            ),
        ]
