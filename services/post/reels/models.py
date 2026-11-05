"""Reels (roadmap 5.5) in ``post_db``.

A reel is a ``Post`` of type ``reel``: the post stays the one authority for
audience, deletion, moderation, reactions, comments and shares. ``Reel`` keeps
what only a reel needs: its video (unique for ever, so one upload is never two
reels), an optional cover, the playable size and length media measured, the
author denormalised for the feeds, and the view counter.

The reel rules are the server's, read from the transcoded media's metadata:
a portrait video around 9:16 (``MIN_ASPECT`` .. ``MAX_ASPECT`` width/height)
of at most ``MAX_DURATION_MS``. Anything else stays a normal video post.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils import timezone
from posts.models import Post

MAX_DURATION_MS = 90_000
# Width / height. 9:16 is 0.5625; taller phones record 9:19.5 (0.46) and 9:20
# (0.45). Up to 2:3 is still "vertical" enough to fill a phone; 3:4 and 4:5 are
# not reels.
MIN_ASPECT = 0.40
MAX_ASPECT = 0.67
MAX_CAPTION = 2200


class PublishState(models.TextChoices):
    """Whether the reel is shown. The reconcile job (``reels.reconcile``) takes a
    reel off the reels surfaces while its video is gone, failed or bound to
    another post, and puts it back once media reports it ready on this post."""

    PUBLISHED = "published", "Published"
    MEDIA_MISSING = "media_missing", "Video deleted"
    MEDIA_FAILED = "media_failed", "Video failed"
    MEDIA_ELSEWHERE = "media_elsewhere", "Video bound to another post"


class Reel(models.Model):
    post = models.OneToOneField(
        Post, on_delete=models.CASCADE, primary_key=True, related_name="reel"
    )
    # Denormalised from the post (a page id when ``author_type`` is ``page``).
    author_id = models.UUIDField()
    author_type = models.CharField(max_length=8, default="user")
    media_id = models.UUIDField(unique=True)
    cover_media_id = models.UUIDField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField()
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    view_count = models.PositiveIntegerField(default=0)
    publish_state = models.CharField(
        max_length=16, choices=PublishState.choices, default=PublishState.PUBLISHED
    )
    # When the reconcile job last looked at this reel's video (oldest first).
    reconciled_at = models.DateTimeField(null=True, blank=True)
    # The publish time (the post's ``created_at``): the feeds' order.
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "reel"
        indexes = [
            models.Index(fields=["-created_at"], name="reel_recent_idx"),
            models.Index(fields=["author_id", "-created_at"], name="reel_author_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(duration_ms__lte=MAX_DURATION_MS), name="reel_max_duration"
            ),
            models.CheckConstraint(condition=Q(height__gt=models.F("width")), name="reel_portrait"),
        ]


class ReelView(models.Model):
    """One view per viewer per reel per (UTC) day; the author's own are not counted."""

    id = models.BigAutoField(primary_key=True)
    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name="views")
    viewer_id = models.UUIDField()
    day = models.DateField()
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reel_view"
        constraints = [
            models.UniqueConstraint(fields=["reel", "viewer_id", "day"], name="reel_view_uniq"),
        ]
        indexes = [models.Index(fields=["viewer_id", "-viewed_at"], name="reel_view_viewer_idx")]


class ReelHide(models.Model):
    """A "not interested" mark: the reel leaves this viewer's reels feeds. Undo deletes the row."""

    id = models.BigAutoField(primary_key=True)
    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name="hides")
    account_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reel_hide"
        constraints = [
            models.UniqueConstraint(fields=["reel", "account_id"], name="reel_hide_uniq"),
        ]
        indexes = [models.Index(fields=["account_id"], name="reel_hide_account_idx")]
