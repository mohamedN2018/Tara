"""Tara Intelligence tables in ``feed_db`` (docs/intelligence/03-database-design.md).

Conventions: every table is prefixed ``intel_``; references to other services are
plain UUID columns (no cross-service ForeignKey); new ids are UUIDv7.

The two telemetry tables are range-partitioned and created by ``RunSQL`` in
``0001_initial``; their models are ``managed = False`` and are used for reads only.
Writes go through ``intel.signals.store`` (``COPY`` for client batches, one
``INSERT`` for a bus or server row).
"""

from __future__ import annotations

import uuid

from django.contrib.postgres.fields import ArrayField
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
    # Accumulated >= 50%-visible time of one card, once per (session, item) (06 5.1).
    FEED_DWELL = "feed_dwell", "Feed dwell"
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
    # R4 (07 WP 7.5-B2; 06 section 7): explicit feedback and group membership changes.
    MUTE_TOPIC = "mute_topic", "Topic muted"
    HIDE_CREATOR = "hide_creator", "Creator hidden"
    GROUP_JOIN = "group_join", "Joined a group"
    GROUP_LEAVE = "group_leave", "Left a group"


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
        EventType.FEED_DWELL,
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
    # The impression rule a ``feed_impression`` row was measured with (1 or 2,
    # ``delivery.impression.def_version``; WP 4c.9-B3); NULL on every other row.
    impression_def = models.SmallIntegerField(null=True)

    class Meta:
        managed = False
        db_table = "intel_signal_event"


class UserItemEngagement(models.Model):
    """Per (account, item) engagement within the retention window (read-only model;
    the table is partitioned by ``first_at`` week). Filled by the aggregator (WP 6.3).

    The exposure columns (06 section 13, 07 WP 4b.13; ``intel/0008``) carry the
    durable half of the exposure ledger: ``state`` is the highest state reached
    (``ExposureState``), ``visits`` the number of distinct visits with at least a
    display, ``consumed_dwell_only`` marks a consumption reached by dwell alone."""

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
    dwell_ms = models.IntegerField(default=0)
    state = models.SmallIntegerField(null=True)
    consumed_dwell_only = models.BooleanField(default=False)
    last_displayed_at = models.DateTimeField(null=True)
    visits = models.SmallIntegerField(default=0)

    class Meta:
        managed = False
        db_table = "intel_user_item_engagement"


class ExposureState(models.IntegerChoices):
    """``intel_user_item_engagement.state`` and the hot ledger's state bits (06 5.1).
    ``retrieved`` has no value on purpose: an item only served is never "seen"."""

    DISPLAYED = 0, "Displayed"
    SKIPPED = 1, "Skipped"
    VIEWED = 2, "Viewed"
    CONSUMED = 3, "Consumed"


# ---- Phase 3: read models built from events (03 sections 2.1 and 2.2) ---------------
# Every writer is newest-wins on its own ``*_at`` guard and safe to replay
# (``intel.readmodels``). None of these tables holds body text or names.


class ContentRef(models.Model):
    """One post, reel or video, kept apart from fan-out (03 section 2.1).

    Fields an event did not carry yet stay empty, and the eligibility rules treat an
    empty field as "not allowed" (fail closed): a row first created by a late
    ``post.approved`` has no audience or author until its ``post.created`` arrives.
    """

    class State(models.TextChoices):
        LIVE = "live", "Live"
        DELETED = "deleted", "Deleted"
        HIDDEN = "hidden", "Hidden (author deactivated)"

    class Moderation(models.TextChoices):
        OK = "ok", "OK"
        PENDING = "pending", "Pending review"
        REMOVED = "removed", "Removed"

    post_id = models.UUIDField(primary_key=True)
    author_id = models.UUIDField(null=True)
    author_type = models.CharField(max_length=8, blank=True, default="")
    type = models.CharField(max_length=8, blank=True, default="")
    audience = models.CharField(max_length=12, blank=True, default="")
    group_id = models.UUIDField(null=True)
    approval_state = models.CharField(max_length=10, blank=True, default="")
    reel_state = models.CharField(max_length=16, blank=True, default="")
    shared_post_id = models.UUIDField(null=True)
    lang = models.CharField(max_length=5, default="und")
    hashtags = ArrayField(models.CharField(max_length=80), default=list, blank=True)
    media_ids = ArrayField(models.UUIDField(), default=list, blank=True)
    # WP 4.4 integrity, from the excerpt at write time (``intel.integrity``): the
    # 64-bit SimHash (signed), the oldest live near-copy it duplicates, the bait score.
    simhash = models.BigIntegerField(null=True)
    dup_of = models.UUIDField(null=True)
    bait_score = models.FloatField(null=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.LIVE)
    # The author's account is deactivated (``post.hidden``): kept apart from
    # ``state`` so an edit or a moderation approval never shows a held post.
    held = models.BooleanField(default=False)
    moderation_state = models.CharField(
        max_length=8, choices=Moderation.choices, default=Moderation.OK
    )
    pending_reports = models.IntegerField(default=0)
    moderation_open = models.BooleanField(default=False)
    created_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Newest-wins guards: content and lifecycle (created, updated, deleted), the
    # deactivation hold (hidden, unhidden), the reel's playability, moderation.
    event_at = models.DateTimeField()
    hidden_at = models.DateTimeField(null=True)
    reel_state_at = models.DateTimeField(null=True)
    moderation_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "intel_content_ref"
        indexes = [
            models.Index(fields=["author_id", "-created_at"], name="intel_cref_author_idx"),
            models.Index(
                fields=["group_id", "-created_at"],
                name="intel_cref_group_idx",
                condition=models.Q(group_id__isnull=False, state="live"),
            ),
            models.Index(
                fields=["type", "-created_at"],
                name="intel_cref_public_idx",
                condition=models.Q(audience="public", group_id__isnull=True, state="live"),
            ),
            models.Index(
                fields=["-created_at"], name="intel_cref_live_idx", condition=models.Q(state="live")
            ),
        ]


class MediaRef(models.Model):
    """A processed video (``media.processed`` with ``kind=video``)."""

    media_id = models.UUIDField(primary_key=True)
    duration_ms = models.IntegerField(null=True)
    width = models.IntegerField(null=True)
    height = models.IntegerField(null=True)
    top_rung = models.SmallIntegerField(null=True)
    has_poster = models.BooleanField(default=False)
    has_audio = models.BooleanField(null=True)
    quality = models.FloatField(default=0.0)
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "intel_media_ref"


class FriendEdge(models.Model):
    """An accepted friendship, stored in both directions. ``active=False`` is the
    tombstone of a removal, so a replayed older ``friendship.accepted`` changes nothing."""

    pk = models.CompositePrimaryKey("account_id", "friend_id")
    account_id = models.UUIDField()
    friend_id = models.UUIDField()
    active = models.BooleanField(default=True)
    since = models.DateTimeField()
    event_at = models.DateTimeField()

    class Meta:
        db_table = "intel_friend_edge"


class GroupRef(models.Model):
    """A group's privacy and status. No name or handle (hidden groups stay out of feed_db)."""

    group_id = models.UUIDField(primary_key=True)
    privacy = models.CharField(max_length=8, default="hidden")
    status = models.CharField(max_length=10, default="active")
    category = models.CharField(max_length=20, blank=True, default="")
    topic_id = models.SmallIntegerField(null=True)  # topics (phase 6)
    member_count = models.IntegerField(default=0)
    event_at = models.DateTimeField()

    class Meta:
        db_table = "intel_group_ref"
        indexes = [models.Index(fields=["privacy", "status"], name="intel_gref_priv_idx")]


class GroupMembership(models.Model):
    """The account's place in a group. ``state=none`` is the tombstone of a leave."""

    pk = models.CompositePrimaryKey("account_id", "group_id")
    account_id = models.UUIDField()
    group_id = models.UUIDField()
    state = models.CharField(max_length=10)  # active, requested, invited, banned, none
    role = models.CharField(max_length=10, blank=True, default="")
    notify_posts = models.BooleanField(default=False)
    joined_at = models.DateTimeField(null=True)
    event_at = models.DateTimeField()

    class Meta:
        db_table = "intel_group_membership"
        indexes = [
            models.Index(
                fields=["group_id"],
                name="intel_gmem_active_idx",
                condition=models.Q(state="active"),
            ),
        ]


class BlockPair(models.Model):
    """A block between two accounts, either way (``low`` is the smaller id).

    Each direction keeps its own flag and newest-wins time, so one side lifting its
    block never lifts the other side's. The row goes when both flags are off.
    """

    pk = models.CompositePrimaryKey("low", "high")
    low = models.UUIDField()
    high = models.UUIDField()
    low_blocks = models.BooleanField(default=False)
    high_blocks = models.BooleanField(default=False)
    low_at = models.DateTimeField(null=True)
    high_at = models.DateTimeField(null=True)
    since = models.DateTimeField()

    class Meta:
        db_table = "intel_block_pair"
        # R3: ``feed.ranking.visible_items`` looks blocks up from either side.
        indexes = [models.Index(fields=["high"], name="intel_block_high_idx")]


class PageRef(models.Model):
    """A page's status and owner (``page.created`` / ``page.updated``). Rule E6b."""

    page_id = models.UUIDField(primary_key=True)
    owner_id = models.UUIDField(null=True)
    status = models.CharField(max_length=10, default="draft")
    deleted = models.BooleanField(default=False)
    event_at = models.DateTimeField()
    # R4 WP 6.2: ``normalize_key(Page.category)`` from ``page.created`` / ``page.updated``
    # (the page-category topic source of the classifier); blank until an event says.
    category_norm = models.CharField(max_length=80, blank=True, default="")

    class Meta:
        db_table = "intel_page_ref"
        indexes = [
            models.Index(
                fields=["status"],
                name="intel_pref_status_idx",
                condition=~models.Q(status="published") | models.Q(deleted=True),
            ),
        ]


class AccountRestriction(models.Model):
    """A moderation ``restrict`` or ``shadow`` on an account (rule E11). Sensitive:
    never shown to its subject. ``active=False`` is the tombstone of a ``reinstate``."""

    account_id = models.UUIDField(primary_key=True)
    kind = models.CharField(max_length=8)  # restrict | shadow
    case_id = models.UUIDField(null=True)
    active = models.BooleanField(default=True)
    since = models.DateTimeField()
    event_at = models.DateTimeField()

    class Meta:
        db_table = "intel_account_restriction"


class FanoutCapped(models.Model):
    """A post whose fan-out was cut at ``FANOUT_MAX_RECIPIENTS``. ``follow_pull``
    reaches the followers the cap left out."""

    post_id = models.UUIDField(primary_key=True)
    author_id = models.UUIDField()
    audience = models.CharField(max_length=12)
    total = models.IntegerField()
    cap = models.IntegerField()
    created_at = models.DateTimeField()

    class Meta:
        db_table = "intel_fanout_capped"
        indexes = [models.Index(fields=["author_id", "-created_at"], name="intel_fcap_author_idx")]


class FeedMode(models.TextChoices):
    """The Home modes (02 section 9). ``recent`` is the strictly chronological one."""

    FOR_YOU = "for_you", "For you"
    FOLLOWING = "following", "Following"
    FRIENDS = "friends", "Friends"
    FAVORITES = "favorites", "Favorites"
    RECENT = "recent", "Most recent"


def _default_discovery_prefs() -> dict:
    return {
        "new_creators": True,
        "trending": True,
        "people_suggestions": True,
        "page_suggestions": True,
        "group_suggestions": True,
        "other_languages": False,
    }


class UserPreference(models.Model):
    """One row per account: My Algorithm settings (03 section 2.3).

    WP 4.6 serves ``default_mode`` only (the remembered Home mode). The other
    columns carry their documented defaults so later phases add behaviour, not
    columns; nothing reads them before the phase that wires them. ``default_mode``
    is empty until the viewer picks a mode: the server default then applies.
    """

    account_id = models.UUIDField(primary_key=True)
    default_mode = models.CharField(max_length=10, choices=FeedMode.choices, blank=True, default="")
    discovery_level = models.SmallIntegerField(default=2)
    # Empty means "the account's own language" (plus ``und``), resolved at read time.
    languages = ArrayField(models.CharField(max_length=5), default=list, blank=True)
    formats = models.JSONField(default=dict, blank=True)
    discovery_prefs = models.JSONField(default=_default_discovery_prefs, blank=True)
    sensitive_inference = models.BooleanField(default=False)
    onboarded_at = models.DateTimeField(null=True, blank=True)
    personalization_off = models.BooleanField(default=False)
    version = models.IntegerField(default=1)  # optimistic concurrency
    updated_at = models.DateTimeField(auto_now=True)
    # R4 (06 section 13): the reset epoch (WP 8.4-B2), the decision-7 search-signal
    # opt-in (WP 8.7-B2, off), and the Home sections customization (WP 8.6-B2: the
    # column only; nothing reads it before the sections composer of R6).
    reset_at = models.DateTimeField(null=True, blank=True)
    search_signal = models.BooleanField(default=False)
    home_sections = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "intel_user_preference"


# ---- Phase 4b (R3): the visit summary (06 sections 4.3 and 13; WP 4b.4) -------------


class FeedSession(models.Model):
    """One row per Home visit: written once at the visit start (``INSERT``) and closed
    lazily at the next visit start (one ``UPDATE`` that flushes the ``feed:sess``
    counters). Backs "last visit" when the Redis hash expired. Never holds item ids or
    topics. Not written under ``personalization_off`` (decision 24); deleted on account
    deletion; kept ``session.feed_session_retention_d`` days (``intel.purge_feed_sessions``)."""

    class Kind(models.TextChoices):
        NEW = "new", "New visit"
        RETURNING = "returning", "Returning"
        LAPSED = "lapsed", "Lapsed"

    id = models.UUIDField(primary_key=True)
    account_id = models.UUIDField()
    client_sid = models.UUIDField(null=True)  # a hint only
    kind = models.CharField(max_length=10, choices=Kind.choices)
    entry_surface = models.CharField(max_length=12)
    started_at = models.DateTimeField()
    last_activity_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True)
    first_pages = models.SmallIntegerField(default=0)
    refreshes = models.SmallIntegerField(default=0)
    displayed = models.IntegerField(default=0)
    consumed = models.IntegerField(default=0)
    new_since_count = models.SmallIntegerField(default=0)
    intent = models.CharField(max_length=16, null=True)  # noqa: DJ001 - stays NULL in R3
    head_overlap = models.FloatField(null=True)
    data_origin = models.CharField(max_length=10, choices=DataOrigin.choices)

    class Meta:
        db_table = "intel_feed_session"
        indexes = [
            models.Index(fields=["account_id", "-started_at"], name="intel_fsess_account_idx"),
            models.Index(fields=["started_at"], name="intel_fsess_started_idx"),
        ]


# ---- Phase 4: the central ranking config (03 section 2.7; WP 4.1) -------------------


class RankingConfig(models.Model):
    """One version of a surface's ranking params. Immutable once it leaves ``draft``:
    ``save()`` refuses a params change and a DB trigger (``intel/0004``) rejects any
    ``UPDATE`` of ``params`` (or a ``DELETE``) of a non-draft row. Exactly one version
    per surface is ``active`` (partial unique constraint)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    surface = models.CharField(max_length=12, choices=Surface.choices)
    version = models.IntegerField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    params = models.JSONField()
    schema_version = models.SmallIntegerField(default=1)
    note = models.CharField(max_length=300, blank=True, default="")
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "intel_ranking_config"
        constraints = [
            models.UniqueConstraint(fields=["surface", "version"], name="intel_rcfg_version_uniq"),
            models.UniqueConstraint(
                fields=["surface"],
                condition=models.Q(status="active"),
                name="intel_rcfg_one_active",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            stored = type(self).objects.filter(pk=self.pk).values_list("status", "params").first()
            if stored and stored[0] != self.Status.DRAFT and stored[1] != self.params:
                raise ValueError(f"{self.surface}@{self.version} is not a draft: params are frozen")
        super().save(*args, **kwargs)


class RankingConfigChange(models.Model):
    """The change log: one row per create, activation, rollback (mirrored to admin's
    ``AuditEntry`` by ``intel.config.changed``). The free-text reason stays here."""

    class Action(models.TextChoices):
        CREATED = "created", "Created"
        ACTIVATED = "activated", "Activated"
        ROLLED_BACK = "rolled_back", "Rolled back"
        PAUSED = "paused", "Paused"
        EXPERIMENT_STARTED = "experiment_started", "Experiment started"
        EXPERIMENT_STOPPED = "experiment_stopped", "Experiment stopped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    surface = models.CharField(max_length=12, choices=Surface.choices)
    from_version = models.IntegerField(null=True, blank=True)
    to_version = models.IntegerField()
    action = models.CharField(max_length=20, choices=Action.choices)
    diff = models.JSONField(default=list, blank=True)
    reason = models.CharField(max_length=500, blank=True, default="")
    actor_id = models.UUIDField(null=True, blank=True)  # null: the system
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "intel_ranking_config_change"
        indexes = [models.Index(fields=["surface", "-created_at"], name="intel_rcfg_change_idx")]


# ---- R4: topics, interests, feedback, My Algorithm, experiments (03 sections 2.3-2.7) --


class Topic(models.Model):
    """A curated bilingual topic (03 section 2.3). Never auto-created. ``sensitive``
    topics (politics, religion, Quran) get no inferred interest row without the
    viewer's opt-in (decision 12) and are only "a topic" in reasons."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        HIDDEN = "hidden", "Hidden"

    id = models.SmallAutoField(primary_key=True)
    slug = models.CharField(max_length=40, unique=True)
    label_ar = models.CharField(max_length=60)
    label_en = models.CharField(max_length=60)
    parent_id = models.SmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE)
    allow_minors = models.BooleanField(default=True)
    sensitive = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "intel_topic"


class TopicAlias(models.Model):
    """``(kind, value_norm) -> topic`` (03 section 2.3). ``value_norm`` is
    ``normalize_key(normalize_ar(value))``; a ``strong`` keyword is enough alone."""

    class Kind(models.TextChoices):
        HASHTAG = "hashtag", "Hashtag"
        PAGE_CATEGORY = "page_category", "Page category"
        GROUP_CATEGORY = "group_category", "Group category"
        MARKET_CATEGORY = "market_category", "Market category"
        KEYWORD = "keyword", "Keyword"

    id = models.BigAutoField(primary_key=True)
    topic_id = models.SmallIntegerField()
    kind = models.CharField(max_length=16, choices=Kind.choices)
    value_norm = models.CharField(max_length=80)
    lang = models.CharField(max_length=3, default="any")  # ar | en | any
    weight = models.FloatField(default=1.0)
    strong = models.BooleanField(default=False)
    source = models.CharField(max_length=14, default="curated")  # curated | llm_suggested
    status = models.CharField(max_length=8, default="active")  # active | pending | rejected
    approved_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "intel_topic_alias"
        constraints = [
            models.UniqueConstraint(fields=["kind", "value_norm"], name="intel_talias_uniq"),
        ]
        indexes = [models.Index(fields=["topic_id"], name="intel_talias_topic_idx")]


class ContentTopic(models.Model):
    """A post's topics (at most 3, confidence >= 0.4; 02 section 14), with the rule
    that found each one (``hashtag``, ``page``, ``group``, ``inherited``, ``lexicon``)."""

    pk = models.CompositePrimaryKey("post_id", "topic_id")
    post_id = models.UUIDField()
    topic_id = models.SmallIntegerField()
    confidence = models.FloatField()
    source = models.CharField(max_length=10)
    classified_at = models.DateTimeField()

    class Meta:
        db_table = "intel_content_topic"
        indexes = [models.Index(fields=["topic_id"], name="intel_ctopic_topic_idx")]


class InterestDim(models.TextChoices):
    TOPIC = "topic", "Topic"
    FORMAT = "format", "Format"
    CREATOR = "creator", "Creator"
    LANG = "lang", "Language"
    MARKET_CAT = "market_cat", "Market category"
    GROUP_CAT = "group_cat", "Group category"


class InterestPolarity(models.TextChoices):
    LIKE = "like", "Like"
    DISLIKE = "dislike", "Dislike"
    MORE = "more", "More"
    LESS = "less", "Less"
    SUPPRESSED = "suppressed", "Suppressed"
    MUTED = "muted", "Muted topic"
    HIDDEN = "hidden", "Hidden creator"


class UserInterest(models.Model):
    """The private interest profile (03 section 2.4, 06 section 7). Explicit rows carry
    a ``polarity`` and never decay; inferred rows carry three lazily decayed
    accumulators (short 3 d, mid 14 d, long 45 d; half-lives in the config). Only the
    owner reads them (``/feed/preferences/profile/``); ``counts`` never holds ids."""

    class Source(models.TextChoices):
        EXPLICIT = "explicit", "Explicit"
        INFERRED = "inferred", "Inferred"

    pk = models.CompositePrimaryKey("account_id", "dim", "key", "source")
    account_id = models.UUIDField()
    dim = models.CharField(max_length=10, choices=InterestDim.choices)
    key = models.CharField(max_length=64)
    source = models.CharField(max_length=8, choices=Source.choices)
    polarity = models.CharField(  # noqa: DJ001 - NULL on inferred rows
        max_length=10, choices=InterestPolarity.choices, null=True, blank=True
    )
    short_v = models.FloatField(default=0.0)
    short_at = models.DateTimeField(null=True, blank=True)
    mid_v = models.FloatField(default=0.0)
    mid_at = models.DateTimeField(null=True, blank=True)
    long_v = models.FloatField(default=0.0)
    long_at = models.DateTimeField(null=True, blank=True)
    events_n = models.IntegerField(default=0)
    counts = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "intel_user_interest"
        indexes = [
            models.Index(fields=["account_id", "dim", "source"], name="intel_uint_account_idx")
        ]


class FeedbackAction(models.Model):
    """One explicit feedback action from the post menu, a reel or a profile (03 section
    2.4; 07 WP 7.1, 7.5-B2). ``before`` is the exact prior state of every interest row
    the action changed, so an undo restores it (never recomputes it)."""

    class Action(models.TextChoices):
        INTERESTED = "interested", "Interested"
        NOT_INTERESTED = "not_interested", "Not interested"
        MORE_LIKE_THIS = "more_like_this", "Show more like this"
        LESS_LIKE_THIS = "less_like_this", "Show less like this"
        MUTE_TOPIC = "mute_topic", "Mute topic"
        HIDE_CREATOR = "hide_creator", "Do not recommend this creator"

    id = models.UUIDField(primary_key=True)
    account_id = models.UUIDField()
    item_type = models.CharField(max_length=8, choices=ItemType.choices)
    item_id = models.UUIDField()
    author_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=16, choices=Action.choices)
    topic_ids = ArrayField(models.SmallIntegerField(), default=list, blank=True)
    topic_id = models.SmallIntegerField(null=True, blank=True)  # mute_topic's topic
    surface = models.CharField(max_length=12, blank=True, default="")
    before = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField()
    undone_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "intel_feedback_action"
        constraints = [
            models.UniqueConstraint(
                fields=["account_id", "item_type", "item_id", "action"],
                condition=models.Q(undone_at__isnull=True),
                name="intel_fbk_live_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["account_id", "-created_at"], name="intel_fbk_account_idx"),
            models.Index(fields=["created_at"], name="intel_fbk_created_idx"),
        ]


class PreferenceChange(models.Model):
    """The undo log of My Algorithm (03 section 2.4). Retention 180 days."""

    class Source(models.TextChoices):
        UI = "ui", "Settings"
        NL_LLM = "nl_llm", "Natural language (LLM)"
        NL_RULES = "nl_rules", "Natural language (rules)"
        FEEDBACK = "feedback", "Feedback"
        ONBOARDING = "onboarding", "Onboarding"
        UNDO = "undo", "Undo"
        RESET = "reset", "Reset recommendations"

    id = models.UUIDField(primary_key=True)
    account_id = models.UUIDField()
    source = models.CharField(max_length=10, choices=Source.choices)
    ops = models.JSONField(default=list, blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    text_sha256 = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    llm_model = models.CharField(max_length=80, null=True, blank=True)  # noqa: DJ001
    undone_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "intel_preference_change"
        indexes = [
            models.Index(fields=["account_id", "-created_at"], name="intel_pchg_account_idx"),
            models.Index(fields=["created_at"], name="intel_pchg_created_idx"),
        ]


class DebugConsent(models.Model):
    """The user's 24 h permission for support to explain their ranking (decision 17)."""

    id = models.UUIDField(primary_key=True)
    account_id = models.UUIDField()
    granted_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "intel_debug_consent"
        indexes = [
            models.Index(fields=["account_id", "-expires_at"], name="intel_dcons_account_idx"),
            models.Index(fields=["granted_at"], name="intel_dcons_granted_idx"),
        ]


class Experiment(models.Model):
    """An A/B experiment on one surface (03 section 2.7; WP 5.4). Each variant names a
    config version of the surface; at most one ``running`` experiment per surface."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"
        STOPPED = "stopped", "Stopped"

    key = models.CharField(max_length=60, primary_key=True)
    surface = models.CharField(max_length=12, choices=Surface.choices)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    salt = models.CharField(max_length=16)
    variants = models.JSONField(default=list)
    audience = models.JSONField(default=dict, blank=True)
    primary_metric = models.CharField(max_length=40, blank=True, default="")
    guardrails = models.JSONField(default=dict, blank=True)
    mde = models.FloatField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "intel_experiment"
        constraints = [
            models.UniqueConstraint(
                fields=["surface"],
                condition=models.Q(status="running"),
                name="intel_exp_one_running",
            ),
        ]


class ExperimentExposure(models.Model):
    """First serve of an account under an experiment (02 section 10.2): written at
    assignment, never from telemetry, once per (experiment, account)."""

    pk = models.CompositePrimaryKey("experiment_key", "account_id")
    experiment_key = models.CharField(max_length=60)
    account_id = models.UUIDField()
    variant = models.CharField(max_length=40)
    surface = models.CharField(max_length=12)
    first_exposed_at = models.DateTimeField()
    data_origin = models.CharField(max_length=10, choices=DataOrigin.choices)

    class Meta:
        db_table = "intel_experiment_exposure"
        indexes = [models.Index(fields=["account_id"], name="intel_expx_account_idx")]


class CreatorQuality(models.Model):
    """Public-facing creator aggregates, rebuilt nightly (03 section 2.5). Rates are
    smoothed with priors from the config; reporter ids never reach this table."""

    author_id = models.UUIDField(primary_key=True)
    followers = models.IntegerField(default=0)
    account_age_days = models.IntegerField(null=True, blank=True)
    posts_30d = models.IntegerField(default=0)
    reach_30d = models.IntegerField(default=0)
    hide_rate = models.FloatField(default=0.0)
    report_rate_90d = models.FloatField(default=0.0)
    removal_rate_90d = models.FloatField(default=0.0)
    completion = models.FloatField(null=True, blank=True)
    comment_depth = models.FloatField(default=0.0)
    originality = models.FloatField(default=0.0)
    quality = models.FloatField(default=0.0)
    is_new = models.BooleanField(default=False)
    computed_at = models.DateTimeField()

    class Meta:
        db_table = "intel_creator_quality"


class IntegrityFlag(models.Model):
    """When ``intel.integrity.flagged`` last went out for a post and signal (WP 7.4:
    at most once per post per ``integrity.flag_cooldown_h``). Ids and rates only."""

    pk = models.CompositePrimaryKey("post_id", "signal")
    post_id = models.UUIDField()
    signal = models.CharField(max_length=14)
    author_id = models.UUIDField()
    rate = models.FloatField()
    distinct_accounts = models.IntegerField()
    flagged_at = models.DateTimeField()

    class Meta:
        db_table = "intel_integrity_flag"
        indexes = [models.Index(fields=["author_id"], name="intel_iflag_author_idx")]


class AccountLanguage(models.Model):
    """The account's app language (``account.updated``; WP 6.6/6.7): the cold-start
    language of recommended items. Newest wins."""

    account_id = models.UUIDField(primary_key=True)
    language = models.CharField(max_length=5)
    event_at = models.DateTimeField()

    class Meta:
        db_table = "intel_account_language"


class AggregateWatermark(models.Model):
    """Exactly-once progress of an accumulating aggregator (the interest tiers):
    advanced in the transaction that applies the deltas."""

    name = models.CharField(max_length=40, primary_key=True)
    hi = models.DateTimeField()

    class Meta:
        db_table = "intel_aggregate_watermark"
