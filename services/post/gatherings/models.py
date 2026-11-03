"""Events (``gatherings``) in ``post_db``: the event, RSVPs, invites, reminders, reports.

Accounts and media are bare UUIDs (services own their data). The outbox,
``BlockedPair`` and idempotency tables are the posts app's: one service, one
outbox.
"""

from __future__ import annotations

from django.db import models
from django.db.models import F, Q

from tara_events.envelope import uuid7

MAX_TITLE = 120
MAX_DESCRIPTION = 5000
MAX_LOCATION = 255
MAX_URL = 500
MAX_CAPACITY = 100_000


class Gathering(models.Model):
    class Audience(models.TextChoices):
        PUBLIC = "public", "Public"
        FRIENDS = "friends", "The host's friends"
        INVITE_ONLY = "invite_only", "Invited people only"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CANCELLED = "cancelled", "Cancelled"
        ENDED = "ended", "Ended"

    class LocationType(models.TextChoices):
        PLACE = "place", "A place"
        ONLINE = "online", "Online"

    class ModerationStatus(models.TextChoices):
        OK = "ok", "OK"
        REMOVED = "removed", "Removed"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    host_id = models.UUIDField()
    host_type = models.CharField(max_length=8, default="user")  # user | page (later)
    page_id = models.UUIDField(null=True, blank=True)  # posting as a Page (roadmap 2.7)
    title = models.CharField(max_length=MAX_TITLE)
    description = models.TextField(blank=True, default="")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")  # IANA name, for display
    location_type = models.CharField(
        max_length=8, choices=LocationType.choices, default=LocationType.PLACE
    )
    location = models.CharField(max_length=MAX_LOCATION, blank=True, default="")
    online_url = models.CharField(max_length=MAX_URL, blank=True, default="")
    cover_media_id = models.UUIDField(null=True, blank=True)
    audience = models.CharField(max_length=12, choices=Audience.choices, default=Audience.PUBLIC)
    capacity = models.PositiveIntegerField(null=True, blank=True)  # going only; null: no limit
    going_count = models.PositiveIntegerField(default=0)
    interested_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    moderation_status = models.CharField(
        max_length=10, choices=ModerationStatus.choices, default=ModerationStatus.OK
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "gathering"
        indexes = [
            models.Index(fields=["starts_at", "id"], name="gathering_starts_idx"),
            models.Index(fields=["host_id", "starts_at"], name="gathering_host_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gte=F("starts_at")),
                name="gathering_ends_after_start",
            ),
            models.CheckConstraint(
                condition=Q(capacity__isnull=True) | Q(capacity__gte=1),
                name="gathering_capacity_positive",
            ),
        ]

    @property
    def is_visible(self) -> bool:
        """Deleted and moderator-removed events are hidden from everyone, the host too."""
        return self.deleted_at is None and self.moderation_status == self.ModerationStatus.OK


class RSVPStatus(models.TextChoices):
    GOING = "going", "Going"
    INTERESTED = "interested", "Interested"
    NOT_GOING = "not_going", "Not going"


class GatheringRSVP(models.Model):
    """One answer per account. Every write locks the gathering row first, so the
    counters and the capacity check never race."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    gathering = models.ForeignKey(Gathering, on_delete=models.CASCADE, related_name="rsvps")
    account_id = models.UUIDField()
    status = models.CharField(max_length=10, choices=RSVPStatus.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "gathering_rsvp"
        constraints = [
            models.UniqueConstraint(fields=["gathering", "account_id"], name="gathering_rsvp_uniq"),
        ]
        indexes = [
            models.Index(
                fields=["gathering", "status", "-updated_at"], name="gathering_rsvp_state_idx"
            ),
            models.Index(fields=["account_id", "status"], name="gathering_rsvp_account_idx"),
        ]


class GatheringInvite(models.Model):
    """The host invited a friend (checked through graph when the invite is made)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    gathering = models.ForeignKey(Gathering, on_delete=models.CASCADE, related_name="invites")
    invitee_id = models.UUIDField()
    inviter_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gathering_invite"
        constraints = [
            models.UniqueConstraint(
                fields=["gathering", "invitee_id"], name="gathering_invite_uniq"
            ),
        ]
        indexes = [models.Index(fields=["invitee_id"], name="gathering_invite_invitee_idx")]


class GatheringReminderLog(models.Model):
    """A reminder window already sent for an event: the unique row makes it once only.
    Rows are cleared when the start time moves, so the new time is reminded too."""

    class Window(models.TextChoices):
        DAY = "24h", "About a day before"
        HOUR = "1h", "About an hour before"

    id = models.BigAutoField(primary_key=True)
    gathering = models.ForeignKey(Gathering, on_delete=models.CASCADE, related_name="reminders")
    kind = models.CharField(max_length=4, choices=Window.choices)
    recipients = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gathering_reminder_log"
        constraints = [
            models.UniqueConstraint(fields=["gathering", "kind"], name="gathering_reminder_uniq"),
        ]


class ReportReason(models.TextChoices):
    """An enum, so ``gathering.reported`` carries no free text."""

    SPAM = "spam", "Spam"
    SCAM = "scam", "Scam or fraud"
    HATE = "hate", "Hate speech"
    VIOLENCE = "violence", "Violence"
    NUDITY = "nudity", "Nudity"
    HARASSMENT = "harassment", "Harassment"
    FALSE_INFORMATION = "false_information", "False information"
    OTHER = "other", "Something else"


class GatheringReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    gathering = models.ForeignKey(Gathering, on_delete=models.CASCADE, related_name="reports")
    reporter_id = models.UUIDField()
    reason = models.CharField(max_length=20, choices=ReportReason.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gathering_report"
        constraints = [
            models.UniqueConstraint(
                fields=["gathering", "reporter_id"], name="gathering_report_uniq"
            ),
        ]
