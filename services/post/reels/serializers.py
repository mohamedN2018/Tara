from __future__ import annotations

from posts.hydration import BatchHintsMixin
from posts.models import CommentPolicy
from rest_framework import serializers

from .models import MAX_CAPTION
from .services import REEL_AUDIENCES


class ReelCreateSerializer(serializers.Serializer):
    media_id = serializers.UUIDField()
    cover_media_id = serializers.UUIDField(required=False, allow_null=True)
    caption = serializers.CharField(
        max_length=MAX_CAPTION, required=False, allow_blank=True, default="", trim_whitespace=False
    )
    audience = serializers.ChoiceField(choices=list(REEL_AUDIENCES), default="public")
    comment_policy = serializers.ChoiceField(
        choices=CommentPolicy.choices, default=CommentPolicy.EVERYONE
    )
    page_id = serializers.UUIDField(required=False, allow_null=True)


class ReelBatchSerializer(BatchHintsMixin):
    ids = serializers.ListField(child=serializers.UUIDField(), max_length=50)


class ReelEligibilitySerializer(serializers.Serializer):
    media_id = serializers.UUIDField()


class ReelInfoSerializer(serializers.Serializer):
    """What only a reel has, under ``reel`` in each item (the rest is the post)."""

    media_id = serializers.UUIDField()
    cover_media_id = serializers.UUIDField(allow_null=True)
    duration_ms = serializers.IntegerField()
    width = serializers.IntegerField()
    height = serializers.IntegerField()
    view_count = serializers.IntegerField()
    viewed_today = serializers.BooleanField()
