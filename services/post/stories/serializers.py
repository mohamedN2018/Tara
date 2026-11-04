from __future__ import annotations

from rest_framework import serializers

from .models import BACKGROUNDS, MAX_TEXT, REACTION_TYPES, CloseFriend, ReportReason, Story


class StoryCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Story.Kind.values)
    audience = serializers.ChoiceField(
        choices=Story.Audience.values, default=Story.Audience.FRIENDS
    )
    text = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=MAX_TEXT, trim_whitespace=True
    )
    background = serializers.ChoiceField(choices=list(BACKGROUNDS), default=BACKGROUNDS[0])
    media_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class StorySerializer(serializers.ModelSerializer):
    """A story as the viewer sees it. Counts are the author's alone (null for
    anyone else); ``seen`` and ``my_reaction`` are the viewer's own state."""

    is_mine = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()
    seen = serializers.SerializerMethodField()
    my_reaction = serializers.SerializerMethodField()
    view_count = serializers.SerializerMethodField()
    reaction_count = serializers.SerializerMethodField()

    class Meta:
        model = Story
        fields = [
            "id",
            "author_id",
            "kind",
            "media_id",
            "text",
            "background",
            "audience",
            "created_at",
            "expires_at",
            "is_mine",
            "is_active",
            "seen",
            "my_reaction",
            "view_count",
            "reaction_count",
        ]

    def _mine(self, obj: Story) -> bool:
        return str(obj.author_id) == str(self.context.get("viewer_id"))

    def get_is_mine(self, obj: Story) -> bool:
        return self._mine(obj)

    def get_is_active(self, obj: Story) -> bool:
        return obj.is_active()

    def get_seen(self, obj: Story) -> bool:
        if self._mine(obj):
            return True
        return obj.id in self.context.get("state", {}).get("seen", set())

    def get_my_reaction(self, obj: Story) -> str | None:
        return self.context.get("state", {}).get("reactions", {}).get(obj.id)

    def get_view_count(self, obj: Story) -> int | None:
        return obj.view_count if self._mine(obj) else None

    def get_reaction_count(self, obj: Story) -> int | None:
        return obj.reaction_count if self._mine(obj) else None


class StoryViewerSerializer(serializers.Serializer):
    account_id = serializers.SerializerMethodField()
    viewed_at = serializers.DateTimeField()
    reaction = serializers.SerializerMethodField()

    def get_account_id(self, obj) -> str:
        return str(obj.viewer_id)

    def get_reaction(self, obj) -> str | None:
        return self.context.get("reactions", {}).get(str(obj.viewer_id))


class ReactSerializer(serializers.Serializer):
    reaction = serializers.ChoiceField(choices=REACTION_TYPES)


class StoryReportSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=ReportReason.values)


class CloseFriendSerializer(serializers.ModelSerializer):
    account_id = serializers.SerializerMethodField()

    class Meta:
        model = CloseFriend
        fields = ["account_id", "created_at"]

    def get_account_id(self, obj: CloseFriend) -> str:
        return str(obj.friend_id)


class CloseFriendAddSerializer(serializers.Serializer):
    account_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=50)
