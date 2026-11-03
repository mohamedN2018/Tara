"""Chat domain models (owns `chat_db`). Only conversation members may access content."""

from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent

MESSAGE_REACTION_TYPES = ["like", "love", "haha", "wow", "sad", "angry"]


class Conversation(models.Model):
    class Type(models.TextChoices):
        DM = "dm", "Direct"
        GROUP = "group", "Group"
        PAGE = "page", "Page"
        MARKETPLACE = "marketplace", "Marketplace"
        SUPPORT = "support", "Support"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    type = models.CharField(max_length=12, choices=Type.choices, default=Type.DM)
    title = models.CharField(max_length=160, blank=True, default="")
    created_by = models.UUIDField()
    listing_id = models.UUIDField(null=True, blank=True)  # marketplace conversations
    # Canonical dedup key: sorted account pair for DMs, or
    # "mkt:<listing>:<buyer>:<seller>" for marketplace threads. Sized for the latter.
    dm_key = models.CharField(max_length=160, null=True, blank=True, unique=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    # Per-conversation message sequence (doc 05 §4.7). Unread = last_seq - last_read_seq.
    # Rows that predate it start with seq_ready=false until `backfill_message_seq`
    # numbers their messages; new conversations are ready from the start.
    last_seq = models.BigIntegerField(default=0, db_default=0)
    seq_ready = models.BooleanField(default=True, db_default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "conversation"
        indexes = [models.Index(fields=["type"], name="conversation_type_idx")]


class ConversationMember(models.Model):
    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        ADMIN = "admin", "Admin"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="members")
    account_id = models.UUIDField()
    role = models.CharField(max_length=8, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)
    muted_until = models.DateTimeField(null=True, blank=True)
    last_read_message_id = models.UUIDField(null=True, blank=True)
    # Pointers only move forward (UPDATE ... WHERE last_read_seq < :new).
    last_read_seq = models.BigIntegerField(default=0, db_default=0)
    last_delivered_seq = models.BigIntegerField(default=0, db_default=0)
    last_read_at = models.DateTimeField(null=True, blank=True)
    # Per-member inbox state: archive, and "clear chat for me" (messages created
    # at or before cleared_at are hidden from this member only).
    archived_at = models.DateTimeField(null=True, blank=True)
    cleared_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "conversation_member"
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "account_id"], name="conversation_member_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["account_id"], name="member_account_idx"),
            models.Index(fields=["account_id", "archived_at"], name="member_account_archived_idx"),
        ]


class Message(models.Model):
    class Type(models.TextChoices):
        TEXT = "text", "Text"
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        FILE = "file", "File"
        AUDIO = "audio", "Audio"
        VOICE = "voice", "Voice note"
        SYSTEM = "system", "System"
        SHARE = "share", "Shared"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender_id = models.UUIDField()
    type = models.CharField(max_length=8, choices=Type.choices, default=Type.TEXT)
    body = models.TextField(blank=True, default="")
    # Arabic-normalised, case-folded copy of `body` for search (text.normalize).
    body_norm = models.TextField(blank=True, default="", db_default="")
    seq = models.BigIntegerField(null=True, blank=True)
    reply_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    # Deleted for everyone by its sender: kept as a tombstone, content wiped.
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.UUIDField(null=True, blank=True)
    # Removed by moderation: hidden entirely, kept apart so it can be reversed.
    moderation_removed_at = models.DateTimeField(null=True, blank=True)
    # Never serialized: forwarding must not leak where the original lives.
    forwarded_from_message_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "message"
        # Partitioned by month at scale (doc 05 §4); single table for now.
        indexes = [
            models.Index(fields=["conversation", "-created_at"], name="message_conv_idx"),
            # `body_norm LIKE '%term%'` (the `contains` lookup) uses this index.
            GinIndex(fields=["body_norm"], opclasses=["gin_trgm_ops"], name="message_body_trgm"),
        ]
        constraints = [
            # NULLs are distinct, so rows not yet numbered never collide.
            models.UniqueConstraint(fields=["conversation", "seq"], name="message_conv_seq_uniq"),
        ]


class MessageAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="attachments")
    media_id = models.UUIDField()
    kind = models.CharField(max_length=12, default="file")
    duration_ms = models.PositiveIntegerField(null=True, blank=True)  # voice/audio
    # Copied from media at send time (media owns the bytes; these are for display).
    mime = models.CharField(max_length=120, blank=True, default="", db_default="")
    bytes = models.BigIntegerField(null=True, blank=True)
    file_name = models.CharField(max_length=200, blank=True, default="", db_default="")
    position = models.PositiveSmallIntegerField(default=0, db_default=0)

    class Meta:
        db_table = "message_attachment"
        indexes = [models.Index(fields=["media_id"], name="attachment_media_idx")]


class MessageReaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="reactions")
    account_id = models.UUIDField()
    type = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "message_reaction"
        constraints = [
            models.UniqueConstraint(fields=["message", "account_id"], name="message_reaction_uniq"),
        ]


class MessageEdit(models.Model):
    """The body a message had before an edit. Removed with delete-for-everyone."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="edits")
    previous_body = models.TextField(blank=True, default="")
    edited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "message_edit"
        indexes = [models.Index(fields=["message", "-edited_at"], name="message_edit_idx")]


class MessageHidden(models.Model):
    """Delete for me: the message is hidden from this member only."""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="hidden_for")
    account_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "message_hidden"
        constraints = [
            models.UniqueConstraint(fields=["message", "account_id"], name="message_hidden_uniq"),
        ]
        indexes = [models.Index(fields=["account_id"], name="message_hidden_account_idx")]


class PinnedMessage(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="pins")
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    pinned_by = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pinned_message"
        constraints = [
            models.UniqueConstraint(fields=["conversation", "message"], name="pinned_message_uniq"),
        ]


class BlockedPair(models.Model):
    blocker_id = models.UUIDField()
    blocked_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "blocked_pair"
        constraints = [
            models.UniqueConstraint(
                fields=["blocker_id", "blocked_id"], name="chat_blocked_pair_uniq"
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
