from __future__ import annotations

from rest_framework import serializers

from .models import REACTION_TYPES, Audience, Comment, Post, SavedItem


class PostCreateSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, default="", max_length=20000)
    type = serializers.ChoiceField(choices=Post.Type.values, default=Post.Type.TEXT)
    audience = serializers.ChoiceField(choices=Audience.values, default=Audience.PUBLIC)
    media_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    shared_post_id = serializers.UUIDField(required=False, allow_null=True)
    link_preview = serializers.DictField(required=False, allow_null=True)


class PostSerializer(serializers.ModelSerializer):
    media_ids = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            "id",
            "author_id",
            "author_type",
            "type",
            "body",
            "audience",
            "shared_post_id",
            "link_preview",
            "media_ids",
            "reaction_count",
            "comment_count",
            "share_count",
            "created_at",
            "updated_at",
        ]

    def get_media_ids(self, obj: Post) -> list[str]:
        return [str(m.media_id) for m in obj.media.all()]


class PostEditSerializer(serializers.Serializer):
    body = serializers.CharField(allow_blank=True, max_length=20000)


class ReactionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=REACTION_TYPES)


class CommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=8000)
    parent_id = serializers.UUIDField(required=False, allow_null=True)


class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ["id", "post_id", "author_id", "parent_id", "body", "created_at"]


class SaveSerializer(serializers.Serializer):
    item_type = serializers.ChoiceField(choices=["post", "listing", "page", "video"])
    item_id = serializers.UUIDField()


class SavedItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedItem
        fields = ["id", "item_type", "item_id", "created_at"]


class ReportSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200)
