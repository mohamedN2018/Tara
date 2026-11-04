from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from .models import (
    MESSAGE_REACTION_TYPES,
    ChatSettings,
    Conversation,
    ConversationMember,
    Message,
    MessageAttachment,
    MessageReaction,
)


class DMCreateSerializer(serializers.Serializer):
    other_id = serializers.UUIDField()


class PageConversationSerializer(serializers.Serializer):
    page_id = serializers.UUIDField()


class ChatSettingsSerializer(serializers.Serializer):
    message_from = serializers.ChoiceField(choices=ChatSettings.MessageFrom.values)


class TeamReplySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=8000)


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
    request_status = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "type",
            "title",
            "listing_id",
            "listing_title",
            "listing_cover_media_id",
            "page_id",
            "last_message_at",
            "last_seq",
            "created_at",
            "members",
            "member_states",
            "muted_until",
            "pinned_messages",
            "unread_count",
            "archived",
            "request_status",
            "last_message",
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

    def get_request_status(self, obj: Conversation) -> str:
        """The viewer's own request state: ``none``, ``pending`` or ``spam``.
        Nobody else's is ever shown (a sender never learns it was declined)."""
        mine = self._mine(obj)
        return (mine.request_status if mine else "") or "none"

    def get_last_message(self, obj: Conversation) -> dict | None:
        """The newest message the viewer can see, for the inbox row."""
        preview = getattr(obj, "last_message_preview", None)
        if not preview:
            return None
        deleted = bool(preview.get("deleted_at"))
        return {
            "id": preview.get("id"),
            "sender_id": preview.get("sender_id"),
            "type": preview.get("type"),
            "body": "" if deleted else (preview.get("body") or ""),
            "deleted": deleted,
            "created_at": preview.get("created_at"),
        }

    def get_muted_until(self, obj: Conversation) -> str | None:
        mine = self._mine(obj)
        if mine is None or mine.muted_until is None or mine.muted_until <= timezone.now():
            return None
        return mine.muted_until.isoformat()

    def get_pinned_messages(self, obj: Conversation) -> list[dict]:
        pins = getattr(obj, "active_pins", None)
        mine = self._mine(obj)
        if pins is None:
            pins = obj.pins.filter(
                message__deleted_at__isnull=True, message__moderation_removed_at__isnull=True
            ).select_related("message")
            if mine is not None:
                pins = pins.exclude(message__hidden_for__account_id=mine.account_id)
        else:
            pins = [p for p in pins if not getattr(p, "hidden_by_viewer", False)]
        if mine is not None:
            # Not what the viewer hid or cleared, nor what a group said before they joined.
            since = mine.cleared_at
            if obj.type == Conversation.Type.GROUP and (since is None or mine.joined_at > since):
                since = mine.joined_at
            if since is not None:
                pins = [p for p in pins if p.message.created_at >= since]
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
        # `reply_visible` (services._with_message_state): false when the viewer
        # cannot open the original, e.g. a group message from before they joined.
        gone = (
            target.deleted_at is not None
            or target.moderation_removed_at is not None
            or getattr(obj, "reply_visible", True) is False
        )
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


class RequestActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["accept", "decline"])


class MessageReportSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(
        choices=[
            "spam",
            "scam",
            "hate",
            "violence",
            "nudity",
            "harassment",
            "false_information",
            "other",
        ]
    )


class MuteSerializer(serializers.Serializer):
    minutes = serializers.IntegerField(min_value=0, max_value=525600, default=480)  # 0 = unmute


class PinSerializer(serializers.Serializer):
    message_id = serializers.UUIDField()


def _preview(obj) -> dict | None:
    preview = getattr(obj, "last_message_preview", None)
    if not preview:
        return None
    deleted = bool(preview.get("deleted_at"))
    return {
        "id": preview.get("id"),
        "sender_id": preview.get("sender_id"),
        "type": preview.get("type"),
        "body": "" if deleted else (preview.get("body") or ""),
        "deleted": deleted,
        "created_at": preview.get("created_at"),
    }


class TeamConversationSerializer(serializers.ModelSerializer):
    """A page or support conversation as its answering team sees it: who wrote
    (``account_id``), the newest message and how much the team has not read."""

    account_id = serializers.SerializerMethodField()
    left = serializers.SerializerMethodField()
    team_unread = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "type",
            "title",
            "page_id",
            "account_id",
            "left",
            "last_message_at",
            "last_seq",
            "team_unread",
            "last_message",
            "created_at",
        ]

    def _member(self, obj):
        members = getattr(obj, "all_members", None)
        if members is None:
            members = list(obj.members.order_by("joined_at"))
        return members[0] if members else None

    def get_account_id(self, obj) -> str | None:
        member = self._member(obj)
        return str(member.account_id) if member else None

    def get_left(self, obj) -> bool:
        member = self._member(obj)
        return member is None or member.left_at is not None

    def get_team_unread(self, obj) -> int:
        return max(0, obj.last_seq - obj.team_read_seq) if obj.seq_ready else 0

    def get_last_message(self, obj) -> dict | None:
        return _preview(obj)


class TeamMessageSerializer(MessageSerializer):
    """The team's copy of a message also says which teammate wrote a reply."""

    class Meta(MessageSerializer.Meta):
        fields = [*MessageSerializer.Meta.fields, "author_id"]
