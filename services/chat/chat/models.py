"""Chat domain models (owns `chat_db`). Only conversation members may access content."""

from __future__ import annotations

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
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "conversation_member"
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "account_id"], name="conversation_member_uniq"
            ),
        ]
        indexes = [models.Index(fields=["account_id"], name="member_account_idx")]


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
    reply_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "message"
        # Partitioned by month at scale (doc 05 §4); single table for now.
        indexes = [models.Index(fields=["conversation", "-created_at"], name="message_conv_idx")]


class MessageAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="attachments")
    media_id = models.UUIDField()
    kind = models.CharField(max_length=12, default="file")
    duration_ms = models.PositiveIntegerField(null=True, blank=True)  # voice/audio

    class Meta:
        db_table = "message_attachment"


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
