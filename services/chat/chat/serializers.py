from __future__ import annotations

from rest_framework import serializers

from .models import MESSAGE_REACTION_TYPES, Conversation, Message, MessageAttachment


class DMCreateSerializer(serializers.Serializer):
    other_id = serializers.UUIDField()


class GroupCreateSerializer(serializers.Serializer):
    member_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    title = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")


class ConversationSerializer(serializers.ModelSerializer):
    members = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ["id", "type", "title", "listing_id", "last_message_at", "created_at", "members"]

    def get_members(self, obj: Conversation) -> list[str]:
        return [str(m.account_id) for m in obj.members.filter(left_at__isnull=True)]


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


class VoiceMessageSerializer(serializers.Serializer):
    media_id = serializers.UUIDField()
    duration_ms = serializers.IntegerField(min_value=1)


class MessageSerializer(serializers.ModelSerializer):
    attachments = AttachmentSerializer(many=True, read_only=True)

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
            "created_at",
            "edited_at",
        ]


class ReactionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=MESSAGE_REACTION_TYPES)


class ReadSerializer(serializers.Serializer):
    up_to_message_id = serializers.UUIDField()


class MuteSerializer(serializers.Serializer):
    minutes = serializers.IntegerField(min_value=0, default=480)  # 0 = unmute


class PinSerializer(serializers.Serializer):
    message_id = serializers.UUIDField()
