from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import services
from .models import AuthorSnooze, FeedItem, PostHide


class FeedItemSerializer(serializers.ModelSerializer):
    # Public posts and the viewer's own posts carry the stored excerpt and media
    # ids; every other item carries ids and enums only (hydrate via /posts/batch/).
    snapshot = serializers.SerializerMethodField()

    class Meta:
        model = FeedItem
        fields = ["id", "post_id", "author_id", "reason", "score", "snapshot", "post_created_at"]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_snapshot(self, item: FeedItem) -> dict:
        return services.snapshot_for(item.snapshot, item.recipient_id, item.author_id)


class HideRequestSerializer(serializers.Serializer):
    post_id = serializers.UUIDField()
    reason = serializers.ChoiceField(choices=PostHide.Reason.choices)


class PostHideSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostHide
        fields = ["post_id", "reason", "hidden_at"]


class SnoozeRequestSerializer(serializers.Serializer):
    author_id = serializers.UUIDField()


class AuthorSnoozeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuthorSnooze
        fields = ["author_id", "until", "snoozed_at"]
