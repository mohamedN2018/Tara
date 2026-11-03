from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from .models import (
    MESSAGE_REACTION_TYPES,
    Conversation,
    ConversationMember,
    Message,
    MessageAttachment,
    MessageReaction,
)


class DMCreateSerializer(serializers.Serializer):
    other_id = serializers.UUIDField()


class GroupUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)


class MembersAddSerializer(serializers.Serializer):
    account_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=256, allow_empty=False
    )


class MemberRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ConversationMember.Role.values)


class GroupCreateSerializer(serializers.Serializer):
    member_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=256, allow_empty=False
    )
    title = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")


class ConversationSerializer(serializers.ModelSerializer):
    """Pass ``context={"viewer_id": ...}`` for ``muted_until``.

    Querysets from ``services.with_state`` avoid per-row member and pin queries.
    """

    members = serializers.SerializerMethodField()
    member_states = serializers.SerializerMethodField()
    muted_until = serializers.SerializerMethodField()
    pinned_messages = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    archived = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "type",
            "title",
            "listing_id",
            "last_message_at",
            "last_seq",
            "created_at",
            "members",
            "member_states",
            "muted_until",
            "pinned_messages",
            "unread_count",
            "archived",
        ]

    def _active(self, obj: Conversation) -> list:
        prefetched = getattr(obj, "active_members", None)
        if prefetched is not None:
            return prefetched
        return list(obj.members.filter(left_at__isnull=True).order_by("joined_at"))

    def get_members(self, obj: Conversation) -> list[str]:
        return [str(m.account_id) for m in self._active(obj)]

    def get_member_states(self, obj: Conversation) -> list[dict]:
        return [
            {
                "account_id": str(m.account_id),
                "role": m.role,
                "last_read_message_id": (
                    str(m.last_read_message_id) if m.last_read_message_id else None
                ),
                "last_read_seq": m.last_read_seq,
                "last_delivered_seq": m.last_delivered_seq,
            }
            for m in self._active(obj)
        ]

    def _mine(self, obj: Conversation):
        viewer = str(self.context.get("viewer_id"))
        return next((m for m in self._active(obj) if str(m.account_id) == viewer), None)

    def get_unread_count(self, obj: Conversation) -> int:
        from .services import unread_for

        mine = self._mine(obj)
        return unread_for(mine, obj) if mine is not None else 0

    def get_archived(self, obj: Conversation) -> bool:
        mine = self._mine(obj)
        return bool(mine and mine.archived_at)

    def get_muted_until(self, obj: Conversation) -> str | None:
        mine = self._mine(obj)
        if mine is None or mine.muted_until is None or mine.muted_until <= timezone.now():
            return None
        return mine.muted_until.isoformat()

    def get_pinned_messages(self, obj: Conversation) -> list[dict]:
        pins = getattr(obj, "active_pins", None)
        if pins is None:
            pins = obj.pins.filter(message__deleted_at__isnull=True).select_related("message")
        return [
            {
                "id": str(p.message_id),
                "sender_id": str(p.message.sender_id),
                "type": p.message.type,
                "body": p.message.body[:140],
            }
            for p in pins
        ]


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageAttachment
        fields = ["media_id", "kind", "duration_ms", "mime", "bytes", "file_name", "position"]


ATTACHMENT_KINDS = ["image", "video", "file", "audio", "voice"]
MAX_ATTACHMENT_MS = 60 * 60 * 1000


class AttachmentInputSerializer(serializers.Serializer):
    media_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=ATTACHMENT_KINDS, default="file")
    duration_ms = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=MAX_ATTACHMENT_MS
    )
    file_name = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, default="", max_length=8000)
    type = serializers.ChoiceField(choices=Message.Type.values, default=Message.Type.TEXT)
    reply_to_id = serializers.UUIDField(required=False, allow_null=True)
    # The count cap is enforced in services, so 11 attachments is a plain 400.
    attachments = AttachmentInputSerializer(many=True, required=False, default=list)


class MessageEditSerializer(serializers.Serializer):
    body = serializers.CharField(allow_blank=True, max_length=8000)


class ForwardSerializer(serializers.Serializer):
    conversation_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=5
    )


class ArchiveSerializer(serializers.Serializer):
    archived = serializers.BooleanField(default=True)


MAX_VOICE_MS = 10 * 60 * 1000


class VoiceMessageSerializer(serializers.Serializer):
    media_id = serializers.UUIDField()
    duration_ms = serializers.IntegerField(min_value=1, max_value=MAX_VOICE_MS)


class MessageReactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageReaction
        fields = ["account_id", "type"]


class MessageSerializer(serializers.ModelSerializer):
    """Querysets from ``services._with_message_state`` avoid per-row queries.

    A message deleted for everyone is a tombstone: ``deleted`` is true and it
    carries no body, attachments or reactions. ``forwarded`` is a flag only;
    where the original lives is never disclosed.
    """

    attachments = AttachmentSerializer(many=True, read_only=True)
    reactions = MessageReactionSerializer(many=True, read_only=True)
    deleted = serializers.SerializerMethodField()
    forwarded = serializers.SerializerMethodField()
    reply_preview = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "conversation_id",
            "sender_id",
            "type",
            "body",
            "seq",
            "reply_to_id",
            "reply_preview",
            "attachments",
            "reactions",
            "created_at",
            "edited_at",
            "deleted",
            "forwarded",
        ]

    def to_representation(self, instance: Message) -> dict:
        data = super().to_representation(instance)
        if instance.deleted_at:
            data.update(body="", attachments=[], reactions=[], edited_at=None)
        return data

    def get_deleted(self, obj: Message) -> bool:
        return obj.deleted_at is not None

    def get_forwarded(self, obj: Message) -> bool:
        return obj.forwarded_from_message_id is not None

    def get_reply_preview(self, obj: Message) -> dict | None:
        target = obj.reply_to if obj.reply_to_id else None
        if target is None:
            return None
        gone = target.deleted_at is not None or target.moderation_removed_at is not None
        return {
            "id": str(target.id),
            "sender_id": str(target.sender_id),
            "type": target.type,
            "body": "" if gone else target.body[:140],
            "deleted": gone,
        }


class SharedMediaSerializer(serializers.ModelSerializer):
    message_id = serializers.UUIDField(source="message.id", read_only=True)
    sender_id = serializers.UUIDField(source="message.sender_id", read_only=True)
    created_at = serializers.DateTimeField(source="message.created_at", read_only=True)

    class Meta:
        model = MessageAttachment
        fields = [
            "id",
            "media_id",
            "kind",
            "mime",
            "bytes",
            "file_name",
            "duration_ms",
            "message_id",
            "sender_id",
            "created_at",
        ]


class ReactionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=MESSAGE_REACTION_TYPES)


class ReadSerializer(serializers.Serializer):
    up_to_message_id = serializers.UUIDField()


class MuteSerializer(serializers.Serializer):
    minutes = serializers.IntegerField(min_value=0, max_value=525600, default=480)  # 0 = unmute


class PinSerializer(serializers.Serializer):
    message_id = serializers.UUIDField()
