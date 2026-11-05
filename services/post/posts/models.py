"""Posts domain models (owns `post_db`)."""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent
from tara_resilience.idempotency import AbstractIdempotencyRecord

REACTION_TYPES = ["like", "love", "care", "haha", "wow", "sad", "angry"]


class Audience(models.TextChoices):
    PUBLIC = "public", "Public"
    FRIENDS = "friends", "Friends"
    FOLLOWERS = "followers", "Followers"
    ONLY_ME = "only_me", "Only me"
    # Forced by the server for a post with a ``group_id`` (roadmap 1.11).
    GROUP = "group", "The group's audience"


class CommentPolicy(models.TextChoices):
    """Who may comment on a post. Enforced by the service, never only by the UI."""

    EVERYONE = "everyone", "Everyone who can see the post"
    FRIENDS = "friends", "The author's friends"
    OFF = "off", "Nobody"


class ApprovalState(models.TextChoices):
    """A group post waits for the group's staff when post approval is on."""

    APPROVED = "approved", "Published"
    PENDING = "pending", "Waiting for the group's approval"


class PostState(models.TextChoices):
    """A draft or a scheduled post is seen by nobody but its author (2C)."""

    PUBLISHED = "published", "Published"
    DRAFT = "draft", "Draft"
    SCHEDULED = "scheduled", "Scheduled"


class TagPolicy(models.TextChoices):
    """Who may tag an account in a post (the "who can tag me" setting)."""

    EVERYONE = "everyone", "Everyone"
    FRIENDS = "friends", "Friends"
    NOBODY = "nobody", "Nobody"


# Feeling and activity keys (2C): a fixed catalogue, translated by the clients.
FEELING_KEYS = (
    "happy",
    "loved",
    "excited",
    "grateful",
    "blessed",
    "proud",
    "relaxed",
    "motivated",
    "hopeful",
    "sad",
    "tired",
    "sick",
)
ACTIVITY_KEYS = (
    "celebrating",
    "traveling",
    "eating",
    "drinking",
    "watching",
    "reading",
    "listening",
    "playing",
    "working",
    "studying",
    "exercising",
    "praying",
)
FEELINGS = FEELING_KEYS + ACTIVITY_KEYS


class Post(models.Model):
    class Type(models.TextChoices):
        TEXT = "text", "Text"
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        LINK = "link", "Link"
        SHARE = "share", "Shared post"
        POLL = "poll", "Poll"
        # A short vertical video (roadmap 5.5): one transcoded video plus a
        # ``reels.Reel`` row; created only through ``/reels/``.
        REEL = "reel", "Reel"

    class ModerationStatus(models.TextChoices):
        OK = "ok", "OK"
        PENDING = "pending", "Pending review"
        REMOVED = "removed", "Removed"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    author_id = models.UUIDField()
    author_type = models.CharField(max_length=8, default="user")  # user | page
    type = models.CharField(max_length=8, choices=Type.choices, default=Type.TEXT)
    body = models.TextField(blank=True, default="")
    audience = models.CharField(max_length=12, choices=Audience.choices, default=Audience.PUBLIC)
    shared_post_id = models.UUIDField(null=True, blank=True)
    link_preview = models.JSONField(null=True, blank=True)
    moderation_status = models.CharField(
        max_length=10, choices=ModerationStatus.choices, default=ModerationStatus.OK
    )
    comment_policy = models.CharField(
        max_length=8, choices=CommentPolicy.choices, default=CommentPolicy.EVERYONE
    )
    # Group posts (roadmap 1.11). The group lives in profile; post keeps a read model.
    group_id = models.UUIDField(null=True, blank=True)
    approval_state = models.CharField(
        max_length=10, choices=ApprovalState.choices, default=ApprovalState.APPROVED
    )
    pinned_at = models.DateTimeField(null=True, blank=True)  # a group announcement
    # Drafts and scheduling (2C). ``created_at`` is set again when a draft or a
    # scheduled post is published, so it is always the publication time.
    state = models.CharField(max_length=10, choices=PostState.choices, default=PostState.PUBLISHED)
    publish_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=120, blank=True, default="")
    feeling = models.CharField(max_length=24, blank=True, default="")
    reaction_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    share_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "post"
        indexes = [
            models.Index(fields=["author_id", "created_at"], name="post_author_idx"),
            # A group's feed (built CONCURRENTLY: the post table is large).
            models.Index(
                fields=["group_id", "-created_at"],
                name="post_group_idx",
                condition=models.Q(group_id__isnull=False),
            ),
            # The publish-scheduled beat task, and an author's drafts list.
            models.Index(
                fields=["publish_at"],
                name="post_scheduled_idx",
                condition=models.Q(state="scheduled"),
            ),
            models.Index(
                fields=["author_id", "-updated_at"],
                name="post_drafts_idx",
                condition=~models.Q(state="published"),
            ),
        ]

    @property
    def is_published(self) -> bool:
        return self.state == PostState.PUBLISHED

    @property
    def is_visible(self) -> bool:
        """Drafts and scheduled posts are not visible, not even to their author
        through the public post API: they have their own endpoints."""
        return (
            self.deleted_at is None
            and self.moderation_status != self.ModerationStatus.REMOVED
            and self.state == PostState.PUBLISHED
        )


class Poll(models.Model):
    """One question per post (the post body), with fixed options and one vote per account."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    post = models.OneToOneField(Post, on_delete=models.CASCADE, related_name="poll")
    closes_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "poll"


class PollOption(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=120)
    position = models.PositiveSmallIntegerField(default=0)
    vote_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "poll_option"
        ordering = ["position"]


class PollVote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="votes")
    option = models.ForeignKey(PollOption, on_delete=models.CASCADE, related_name="votes")
    account_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "poll_vote"
        constraints = [
            models.UniqueConstraint(fields=["poll", "account_id"], name="poll_vote_uniq"),
        ]


class PostMedia(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="media")
    media_id = models.UUIDField()
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "post_media"
        ordering = ["position"]
        # "Is this media already on a post?" runs on every post with media.
        indexes = [models.Index(fields=["media_id"], name="post_media_media_idx")]


class PostReaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reactions")
    account_id = models.UUIDField()
    type = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "post_reaction"
        constraints = [
            models.UniqueConstraint(fields=["post", "account_id"], name="post_reaction_uniq"),
        ]


class PostReactionCount(models.Model):
    """How many reactions of each type a post has, kept with each reaction write."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reaction_counts")
    type = models.CharField(max_length=8)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "post_reaction_count"
        constraints = [
            models.UniqueConstraint(fields=["post", "type"], name="post_reaction_count_uniq"),
        ]


class Comment(models.Model):
    """Two levels only: ``parent`` is always the thread root (null for a root), and
    ``reply_to`` is the comment that was answered, which may itself be a reply."""

    class ModerationStatus(models.TextChoices):
        OK = "ok", "OK"
        REMOVED = "removed", "Removed"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author_id = models.UUIDField()
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies"
    )
    reply_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    body = models.TextField()
    reply_count = models.PositiveIntegerField(default=0)  # live replies, on roots only
    reaction_count = models.PositiveIntegerField(default=0)
    moderation_status = models.CharField(
        max_length=10, choices=ModerationStatus.choices, default=ModerationStatus.OK
    )
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "comment"
        indexes = [
            models.Index(fields=["post", "created_at"], name="comment_post_idx"),
            models.Index(fields=["parent", "created_at"], name="comment_parent_idx"),
        ]


class CommentReaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="reactions")
    account_id = models.UUIDField()
    type = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "comment_reaction"
        constraints = [
            models.UniqueConstraint(fields=["comment", "account_id"], name="comment_reaction_uniq"),
        ]


class CommentReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="reports")
    reporter_id = models.UUIDField()
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "comment_report"
        constraints = [
            models.UniqueConstraint(fields=["comment", "reporter_id"], name="comment_report_uniq"),
        ]


class Share(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="shares")
    account_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "share"


class Hashtag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tag = models.CharField(max_length=80, unique=True)

    class Meta:
        db_table = "hashtag"


class PostHashtag(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="hashtags")
    hashtag = models.ForeignKey(Hashtag, on_delete=models.CASCADE, related_name="posts")

    class Meta:
        db_table = "post_hashtag"
        constraints = [
            models.UniqueConstraint(fields=["post", "hashtag"], name="post_hashtag_uniq"),
        ]


class Mention(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, null=True, blank=True, related_name="mentions"
    )
    comment = models.ForeignKey(
        Comment, on_delete=models.CASCADE, null=True, blank=True, related_name="mentions"
    )
    mentioned_handle = models.CharField(max_length=30)

    class Meta:
        db_table = "mention"


class PostTag(models.Model):
    """A person tagged in a post (2C). Checked against blocks and the tagged
    account's ``who_can_tag`` setting when added; the tagged person may remove it."""

    id = models.BigAutoField(primary_key=True)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="tags")
    account_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "post_tag"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["post", "account_id"], name="post_tag_uniq"),
        ]
        indexes = [models.Index(fields=["account_id"], name="post_tag_account_idx")]


class PostSettings(models.Model):
    """An account's post settings kept by post (2C). No row means the defaults."""

    account_id = models.UUIDField(primary_key=True)
    who_can_tag = models.CharField(
        max_length=8, choices=TagPolicy.choices, default=TagPolicy.FRIENDS
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "post_account_settings"


class SavedCollection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    owner_id = models.UUIDField()
    name = models.CharField(max_length=80, default="Saved")
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "saved_collection"
        indexes = [models.Index(fields=["owner_id"], name="saved_collection_owner_idx")]


class SavedItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    owner_id = models.UUIDField()
    collection = models.ForeignKey(SavedCollection, on_delete=models.CASCADE, related_name="items")
    item_type = models.CharField(max_length=16)  # post | listing | page | video
    item_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "saved_item"
        constraints = [
            models.UniqueConstraint(
                fields=["owner_id", "item_type", "item_id"], name="saved_item_uniq"
            ),
        ]


class PostReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reports")
    reporter_id = models.UUIDField()
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "post_report"
        constraints = [
            # One report per account per post; repeats are no-ops.
            models.UniqueConstraint(fields=["post", "reporter_id"], name="post_report_uniq"),
        ]


class BlockedPair(models.Model):
    """Local read-model from user.blocked/unblocked for hiding content."""

    blocker_id = models.UUIDField()
    blocked_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "blocked_pair"
        constraints = [
            models.UniqueConstraint(
                fields=["blocker_id", "blocked_id"], name="post_blocked_pair_uniq"
            ),
        ]


# ---- group read model (fed by profile's group.* events, roadmap 1.11) ----------------


class GroupRef(models.Model):
    """A group as post knows it. ``last_event_at`` is the source ``occurred_at``:
    older events are ignored (retries reorder them). A deleted group stays as a
    tombstone, so a late ``group.updated`` cannot bring it back."""

    group_id = models.UUIDField(primary_key=True)
    handle = models.CharField(max_length=30, blank=True, default="")  # blank when hidden
    privacy = models.CharField(max_length=8, default="hidden")  # public | private | hidden
    post_approval = models.BooleanField(default=False)
    status = models.CharField(max_length=10, default="active")  # active | suspended | deleted
    last_event_at = models.DateTimeField()

    class Meta:
        db_table = "group_ref"


class GroupMembership(models.Model):
    """An account's role and state in a group. ``state="none"`` is a tombstone
    (left, removed, declined, unbanned), never a deleted row."""

    id = models.BigAutoField(primary_key=True)
    group_id = models.UUIDField()
    account_id = models.UUIDField()
    role = models.CharField(max_length=10, blank=True, default="")  # "" once the row ended
    state = models.CharField(max_length=10)  # requested | invited | active | banned | none
    notify_posts = models.BooleanField(default=False)
    last_event_at = models.DateTimeField()

    class Meta:
        db_table = "group_membership"
        constraints = [
            models.UniqueConstraint(
                fields=["group_id", "account_id"], name="group_membership_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["account_id", "state"], name="group_membership_account_idx"),
            models.Index(fields=["group_id", "state", "role"], name="group_membership_state_idx"),
        ]


class GroupReportReview(models.Model):
    """A group moderator kept a reported post or comment: it leaves the group's
    reported-content queue until it is reported again."""

    id = models.BigAutoField(primary_key=True)
    group_id = models.UUIDField()
    target_type = models.CharField(max_length=8)  # post | comment
    target_id = models.UUIDField()
    reviewed_by = models.UUIDField()
    reviewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "group_report_review"
        constraints = [
            models.UniqueConstraint(
                fields=["target_type", "target_id"], name="group_report_review_uniq"
            ),
        ]


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
