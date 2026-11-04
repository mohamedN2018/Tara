"""Stories (roadmap 1.9) in ``post_db``: the story, its views, reactions and
reports, and each account's close friends list.

Accounts and media are bare UUIDs (services own their data). A story lives for
``STORY_TTL``; after that only its author sees it (the archive). Nothing is
purged: ``expires_at`` decides.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db import models
from django.db.models import Q
from django.utils import timezone
from gatherings.models import ReportReason  # the same enum on every report event
from posts.models import REACTION_TYPES

from tara_events.envelope import uuid7

STORY_TTL = timedelta(hours=24)
MAX_TEXT = 500
# Text-story backgrounds: names of brand gradients, so the client owns the look
# and the server stores an enum, never a colour value.
BACKGROUNDS = ("violet", "dusk", "magenta", "night", "aurora", "sunset")

__all__ = ["REACTION_TYPES", "ReportReason"]


def _expires() -> datetime:
    return timezone.now() + STORY_TTL


class Story(models.Model):
    class Kind(models.TextChoices):
        PHOTO = "photo", "Photo"
        TEXT = "text", "Text"

    class Audience(models.TextChoices):
        PUBLIC = "public", "Public"
        FRIENDS = "friends", "Friends"
        CLOSE_FRIENDS = "close_friends", "Close friends"

    class ModerationStatus(models.TextChoices):
        OK = "ok", "OK"
        REMOVED = "removed", "Removed"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    author_id = models.UUIDField()
    kind = models.CharField(max_length=8, choices=Kind.choices)
    media_id = models.UUIDField(null=True, blank=True)
    # A text story's text, or a photo's caption.
    text = models.CharField(max_length=MAX_TEXT, blank=True, default="")
    background = models.CharField(max_length=16, default=BACKGROUNDS[0])
    audience = models.CharField(max_length=16, choices=Audience.choices, default=Audience.FRIENDS)
    view_count = models.PositiveIntegerField(default=0)
    reaction_count = models.PositiveIntegerField(default=0)
    moderation_status = models.CharField(
        max_length=10, choices=ModerationStatus.choices, default=ModerationStatus.OK
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(default=_expires)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "story"
        indexes = [
            models.Index(fields=["author_id", "expires_at"], name="story_author_expiry_idx"),
            models.Index(fields=["expires_at", "author_id"], name="story_expiry_idx"),
            models.Index(fields=["media_id"], name="story_media_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(kind="photo") | Q(media_id__isnull=False),
                name="story_photo_has_media",
            ),
            models.CheckConstraint(
                condition=~Q(kind="text") | ~Q(text=""),
                name="story_text_not_blank",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=models.F("created_at")),
                name="story_expires_after_create",
            ),
        ]

    @property
    def is_live(self) -> bool:
        """Deleted and moderator-removed stories are hidden from everyone."""
        return self.deleted_at is None and self.moderation_status == self.ModerationStatus.OK

    def is_active(self, now=None) -> bool:
        return self.expires_at > (now or timezone.now())


class StoryView(models.Model):
    """The first time an account other than the author opened the story."""

    id = models.BigAutoField(primary_key=True)
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="views")
    viewer_id = models.UUIDField()
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "story_view"
        constraints = [
            models.UniqueConstraint(fields=["story", "viewer_id"], name="story_view_uniq"),
        ]
        indexes = [
            models.Index(fields=["story", "-viewed_at", "-id"], name="story_view_list_idx"),
            models.Index(fields=["viewer_id", "story"], name="story_view_viewer_idx"),
        ]


class StoryReaction(models.Model):
    """One reaction per account per story; reacting again changes it."""

    id = models.BigAutoField(primary_key=True)
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="reactions")
    account_id = models.UUIDField()
    reaction = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "story_reaction"
        constraints = [
            models.UniqueConstraint(fields=["story", "account_id"], name="story_reaction_uniq"),
        ]


class StoryReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="reports")
    reporter_id = models.UUIDField()
    reason = models.CharField(max_length=20, choices=ReportReason.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "story_report"
        constraints = [
            models.UniqueConstraint(fields=["story", "reporter_id"], name="story_report_uniq"),
        ]


class CloseFriend(models.Model):
    """``owner`` lists ``friend``: ``close_friends`` stories of the owner reach the
    friend while the two are still friends (graph is the source of truth)."""

    id = models.BigAutoField(primary_key=True)
    owner_id = models.UUIDField()
    friend_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "close_friend"
        constraints = [
            models.UniqueConstraint(fields=["owner_id", "friend_id"], name="close_friend_uniq"),
            models.CheckConstraint(
                condition=~Q(owner_id=models.F("friend_id")), name="close_friend_not_self"
            ),
        ]
        indexes = [
            models.Index(fields=["owner_id", "-created_at", "-id"], name="close_friend_owner_idx"),
            models.Index(fields=["friend_id"], name="close_friend_friend_idx"),
        ]
