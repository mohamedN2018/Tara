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

    class Meta:
        model = Conversation
        fields = [
            "id",
            "type",
            "title",
            "listing_id",
            "last_message_at",
            "created_at",
            "members",
            "member_states",
            "muted_until",
            "pinned_messages",
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
            }
            for m in self._active(obj)
        ]

    def get_muted_until(self, obj: Conversation) -> str | None:
        viewer = str(self.context.get("viewer_id"))
        mine = next((m for m in self._active(obj) if str(m.account_id) == viewer), None)
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
        fields = ["media_id", "kind", "duration_ms"]


class AttachmentInputSerializer(serializers.Serializer):
    media_id = serializers.UUIDField()
    kind = serializers.CharField(max_length=12, default="file")
    duration_ms = serializers.IntegerField(required=False, allow_null=True)


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, default="", max_length=8000)
    type = serializers.ChoiceField(choices=Message.Type.values, default=Message.Type.TEXT)
    reply_to_id = serializers.UUIDField(required=False, allow_null=True)
    attachments = AttachmentInputSerializer(many=True, required=False, default=list)


MAX_VOICE_MS = 10 * 60 * 1000


class VoiceMessageSerializer(serializers.Serializer):
    media_id = serializers.UUIDField()
    duration_ms = serializers.IntegerField(min_value=1, max_value=MAX_VOICE_MS)


class MessageReactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageReaction
        fields = ["account_id", "type"]


class MessageSerializer(serializers.ModelSerializer):
    attachments = AttachmentSerializer(many=True, read_only=True)
    reactions = MessageReactionSerializer(many=True, read_only=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "conversation_id",
            "sender_id",
            "type",
            "body",
            "reply_to_id",
            "attachments",
            "reactions",
            "created_at",
            "edited_at",
        ]


class ReactionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=MESSAGE_REACTION_TYPES)


class ReadSerializer(serializers.Serializer):
    up_to_message_id = serializers.UUIDField()


class MuteSerializer(serializers.Serializer):
    minutes = serializers.IntegerField(min_value=0, max_value=525600, default=480)  # 0 = unmute


class PinSerializer(serializers.Serializer):
    message_id = serializers.UUIDField()
