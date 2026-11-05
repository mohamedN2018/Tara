"""Tara Intelligence tables in ``feed_db`` (docs/intelligence/03-database-design.md).

Conventions: every table is prefixed ``intel_``; references to other services are
plain UUID columns (no cross-service ForeignKey); new ids are UUIDv7.

The two telemetry tables are range-partitioned and created by ``RunSQL`` in
``0001_initial``; their models are ``managed = False`` and are used for reads only.
Writes go through ``intel.signals.store`` (``COPY`` for client batches, one
``INSERT`` for a bus or server row).
"""

from __future__ import annotations

from django.core.validators import RegexValidator
from django.db import models


class DataOrigin(models.TextChoices):
    """Where a row comes from. Decided by the ``intel_synthetic_account`` label only."""

    REAL = "real", "Real"
    SYNTHETIC = "synthetic", "Synthetic (seed)"
    TEST = "test", "Test fixture"


class SignalSource(models.TextChoices):
    CLIENT = "client", "Client telemetry"
    BUS = "bus", "Domain event"
    SERVER = "server", "Server action"


class Surface(models.TextChoices):
    HOME = "home", "Home"
    REELS = "reels", "Reels"
    VIDEO = "video", "Video"
    GROUPS = "groups", "Groups"
    MARKETPLACE = "marketplace", "Marketplace"
    DISCOVERY = "discovery", "Discovery"
    PROFILE = "profile", "Profile"
    SEARCH = "search", "Search"
    LINK = "link", "Shared link"


class ItemType(models.TextChoices):
    POST = "post", "Post"
    REEL = "reel", "Reel"
    VIDEO = "video", "Video"
    PROFILE = "profile", "Profile"
    PAGE = "page", "Page"
    GROUP = "group", "Group"
    LISTING = "listing", "Listing"


class EventType(models.TextChoices):
    """Every signal type. Client types come from ``POST /feed/signals/``; the rest
    are derived by the server (bus events, server actions) and refused from a client."""

    # Client telemetry (03 section 4.4).
    FEED_IMPRESSION = "feed_impression", "Impression"
    POST_OPEN = "post_open", "Post opened"
    VIDEO_START = "video_start", "Video started"
    VIDEO_PROGRESS = "video_progress", "Video progress"
    VIDEO_COMPLETE = "video_complete", "Video completed"
    VIDEO_REWATCH = "video_rewatch", "Video rewatched"
    VIDEO_SKIP = "video_skip", "Video skipped"
    REEL_VIEW = "reel_view", "Reel viewed"
    PROFILE_VISIT = "profile_visit", "Profile visited"
    # Bus (domain events, authoritative).
    POST_LIKE = "post_like", "Reacted"
    POST_UNLIKE = "post_unlike", "Reaction removed"
    POST_COMMENT = "post_comment", "Commented"
    POST_SHARE = "post_share", "Shared"
    POST_SAVE = "post_save", "Saved"
    POST_UNSAVE = "post_unsave", "Unsaved"
    POST_REPORT = "post_report", "Reported"
    FOLLOW = "follow", "Followed"
    UNFOLLOW = "unfollow", "Unfollowed"
    MUTE = "mute", "Muted"
    UNMUTE = "unmute", "Unmuted"
    BLOCK = "block", "Blocked"
    UNBLOCK = "unblock", "Unblocked"
    # Server actions (post menu, feedback).
    POST_HIDE = "post_hide", "Hidden"
    POST_UNHIDE = "post_unhide", "Hide undone"
    AUTHOR_SNOOZE = "author_snooze", "Author snoozed"
    AUTHOR_UNSNOOZE = "author_unsnooze", "Snooze undone"
    INTERESTED = "interested", "Interested"
    NOT_INTERESTED = "not_interested", "Not interested"
    MORE_LIKE_THIS = "more_like_this", "Show more like this"
    LESS_LIKE_THIS = "less_like_this", "Show less like this"


CLIENT_EVENT_TYPES = frozenset(
    {
        EventType.FEED_IMPRESSION,
        EventType.POST_OPEN,
        EventType.VIDEO_START,
        EventType.VIDEO_PROGRESS,
        EventType.VIDEO_COMPLETE,
        EventType.VIDEO_REWATCH,
        EventType.VIDEO_SKIP,
        EventType.REEL_VIEW,
        EventType.PROFILE_VISIT,
    }
)
SERVER_ONLY_EVENT_TYPES = frozenset(set(EventType.values) - {str(t) for t in CLIENT_EVENT_TYPES})


class SignalFlag:
    """Bits of ``intel_signal_event.flags``. Aggregation ignores flagged rows except
    for the viewer's own profile (02 section 12.2)."""

    TS_CLAMPED = 1
    WATCH_CLAMPED = 2
    INELIGIBLE_ITEM = 4


_LABEL = RegexValidator(
    r"^(seed|test)-[a-z0-9][a-z0-9._-]*$",
    "A label starts with seed- (synthetic) or test- (test), then lowercase letters, "
    "digits, dot, dash or underscore.",
)


class SyntheticAccount(models.Model):
    """An account whose behaviour is synthetic (seed data) or a test fixture.

    The label alone decides the origin of its rows: ``seed-*`` gives ``synthetic``,
    ``test-*`` gives ``test``. No request field can set an origin. In production the
    table must be empty (readiness check ``intel_synthetic``).
    """

    account_id = models.UUIDField(primary_key=True)
    label = models.CharField(max_length=40, validators=[_LABEL])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "intel_synthetic_account"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(label__startswith="seed-") | models.Q(label__startswith="test-"),
                name="intel_synthetic_label_prefix",
            ),
        ]

    @property
    def origin(self) -> str:
        return DataOrigin.SYNTHETIC if self.label.startswith("seed-") else DataOrigin.TEST


class SignalBatch(models.Model):
    """Batch-level dedupe for ``POST /feed/signals/``: a retried batch is a no-op.

    Written in the same transaction as the batch's ``COPY``; purged after 48 h.
    """

    pk = models.CompositePrimaryKey("account_id", "batch_id")
    account_id = models.UUIDField()
    batch_id = models.UUIDField()
    received_at = models.DateTimeField()

    class Meta:
        db_table = "intel_signal_batch"
        indexes = [models.Index(fields=["received_at"], name="intel_sigbatch_recv_idx")]


class SignalEvent(models.Model):  # noqa: DJ001 - NULL means "not attributed", not ""
    """One telemetry row (read-only model; the table is partitioned by ``received_at`` day)."""

    id = models.UUIDField(primary_key=True)
    client_event_id = models.UUIDField(null=True)
    batch_id = models.UUIDField(null=True)
    account_id = models.UUIDField()
    session_id = models.UUIDField(null=True)
    event_type = models.CharField(max_length=24, choices=EventType.choices)
    item_type = models.CharField(max_length=8, choices=ItemType.choices)
    item_id = models.UUIDField()
    author_id = models.UUIDField(null=True)
    surface = models.CharField(max_length=12, choices=Surface.choices, null=True)  # noqa: DJ001
    position = models.SmallIntegerField(null=True)
    watch_ms = models.IntegerField(null=True)
    pos_ms = models.IntegerField(null=True)
    duration_ms = models.IntegerField(null=True)
    play_index = models.SmallIntegerField(null=True)
    source = models.CharField(max_length=8, choices=SignalSource.choices)
    rank_source = models.CharField(max_length=16, null=True)  # noqa: DJ001
    attributed = models.BooleanField(default=False)
    cfg_version = models.CharField(max_length=24, null=True)  # noqa: DJ001
    variant = models.CharField(max_length=16, null=True)  # noqa: DJ001
    pred = models.BinaryField(null=True)
    flags = models.SmallIntegerField(default=0)
    data_origin = models.CharField(max_length=10, choices=DataOrigin.choices)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "intel_signal_event"


class UserItemEngagement(models.Model):
    """Per (account, item) engagement within the retention window (read-only model;
    the table is partitioned by ``first_at`` week). Filled by the aggregator (WP 6.3)."""

    pk = models.CompositePrimaryKey("account_id", "item_id", "first_at")
    account_id = models.UUIDField()
    item_id = models.UUIDField()
    item_type = models.CharField(max_length=8, choices=ItemType.choices)
    impressions = models.SmallIntegerField(default=0)
    opens = models.SmallIntegerField(default=0)
    max_watch_ms = models.IntegerField(default=0)
    completions = models.SmallIntegerField(default=0)
    rewatches = models.SmallIntegerField(default=0)
    skips = models.SmallIntegerField(default=0)
    positive = models.SmallIntegerField(default=0)
    negative = models.SmallIntegerField(default=0)
    first_at = models.DateTimeField()
    last_at = models.DateTimeField()
    data_origin = models.CharField(max_length=10, choices=DataOrigin.choices)

    class Meta:
        managed = False
        db_table = "intel_user_item_engagement"
