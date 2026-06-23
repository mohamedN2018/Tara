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


class Post(models.Model):
    class Type(models.TextChoices):
        TEXT = "text", "Text"
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        LINK = "link", "Link"
        SHARE = "share", "Shared post"
        POLL = "poll", "Poll"  # architecture placeholder

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
    reaction_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    share_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "post"
        indexes = [models.Index(fields=["author_id", "created_at"], name="post_author_idx")]

    @property
    def is_visible(self) -> bool:
        return self.deleted_at is None and self.moderation_status != self.ModerationStatus.REMOVED


class PostMedia(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="media")
    media_id = models.UUIDField()
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "post_media"
        ordering = ["position"]


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


class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author_id = models.UUIDField()
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies"
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "comment"
        indexes = [models.Index(fields=["post", "created_at"], name="comment_post_idx")]


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
