from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from .models import (
    REACTION_TYPES,
    Audience,
    Comment,
    CommentPolicy,
    Post,
    PostReaction,
    SavedItem,
)


class PollCreateSerializer(serializers.Serializer):
    options = serializers.ListField(
        child=serializers.CharField(max_length=120), min_length=2, max_length=6
    )
    duration_hours = serializers.IntegerField(
        min_value=1, max_value=24 * 7, required=False, allow_null=True
    )

    def validate_options(self, value):
        if len({o.strip().lower() for o in value}) != len(value):
            raise serializers.ValidationError("Options must be different.")
        return [o.strip() for o in value]


class PostCreateSerializer(serializers.Serializer):
    """Shares go through ``posts/<id>/share/``, and link previews are built by the
    server, so neither ``shared_post_id`` nor ``link_preview`` is accepted here."""

    body = serializers.CharField(required=False, allow_blank=True, default="", max_length=20000)
    type = serializers.ChoiceField(
        choices=[Post.Type.TEXT, Post.Type.IMAGE, Post.Type.VIDEO], default=Post.Type.TEXT
    )
    audience = serializers.ChoiceField(choices=Audience.values, default=Audience.PUBLIC)
    comment_policy = serializers.ChoiceField(
        choices=CommentPolicy.values, default=CommentPolicy.EVERYONE
    )
    # The service caps the count (MAX_MEDIA_PER_POST); this only bounds the payload.
    media_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list, max_length=50
    )
    poll = PollCreateSerializer(required=False)

    def validate(self, attrs):
        if attrs.get("poll") and not attrs.get("body", "").strip():
            raise serializers.ValidationError({"body": "A poll needs a question."})
        return attrs


class ShareCreateSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, default="", max_length=20000)
    audience = serializers.ChoiceField(choices=Audience.values, required=False)


class VoteSerializer(serializers.Serializer):
    option_id = serializers.UUIDField()


def poll_data(poll, my_option_id) -> dict:
    options = list(poll.options.all())
    return {
        "id": str(poll.id),
        "closes_at": poll.closes_at.isoformat() if poll.closes_at else None,
        "closed": bool(poll.closes_at and poll.closes_at <= timezone.now()),
        "total_votes": sum(o.vote_count for o in options),
        "my_option_id": str(my_option_id) if my_option_id else None,
        "options": [{"id": str(o.id), "text": o.text, "vote_count": o.vote_count} for o in options],
    }


class PostSerializer(serializers.ModelSerializer):
    """Pass ``context={"viewer_state": ...}`` to include the viewer's own state."""

    media_ids = serializers.SerializerMethodField()
    my_reaction = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField()
    poll = serializers.SerializerMethodField()
    shared_post = serializers.SerializerMethodField()
    reaction_counts = serializers.SerializerMethodField()

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
            "reaction_counts",
            "comment_count",
            "share_count",
            "comment_policy",
            "my_reaction",
            "is_saved",
            "poll",
            "shared_post",
            "created_at",
            "updated_at",
        ]

    def get_media_ids(self, obj: Post) -> list[str]:
        return [str(m.media_id) for m in obj.media.all()]

    def get_reaction_counts(self, obj: Post) -> dict[str, int]:
        """``{type: count}`` for the types this post has, most used first."""
        counts = [(c.type, c.count) for c in obj.reaction_counts.all() if c.count > 0]
        return dict(sorted(counts, key=lambda tc: (-tc[1], REACTION_TYPES.index(tc[0]))))

    def get_my_reaction(self, obj: Post) -> str | None:
        state = self.context.get("viewer_state")
        return state["reactions"].get(obj.id) if state else None

    def get_is_saved(self, obj: Post) -> bool:
        state = self.context.get("viewer_state")
        return obj.id in state["saved"] if state else False

    def get_poll(self, obj: Post) -> dict | None:
        if obj.type != Post.Type.POLL:
            return None
        poll = getattr(obj, "poll", None)
        if poll is None:
            return None
        state = self.context.get("viewer_state") or {}
        return poll_data(poll, state.get("votes", {}).get(poll.id))

    def get_shared_post(self, obj: Post) -> dict | None:
        """The original, if this viewer may see it; ``shared_post_id`` alone means they may not."""
        if not obj.shared_post_id:
            return None
        state = self.context.get("viewer_state") or {}
        original = state.get("shared", {}).get(obj.shared_post_id)
        if original is None:
            return None
        return {
            "id": str(original.id),
            "author_id": str(original.author_id),
            "author_type": original.author_type,
            "type": original.type,
            "body": original.body,
            "audience": original.audience,
            "media_ids": [str(m.media_id) for m in original.media.all()],
            "link_preview": original.link_preview,
            "created_at": original.created_at.isoformat(),
        }


class PostBatchSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), max_length=50)


class PostEditSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    audience = serializers.ChoiceField(choices=Audience.values, required=False)
    comment_policy = serializers.ChoiceField(choices=CommentPolicy.values, required=False)

    def validate(self, attrs):
        if not {"body", "audience", "comment_policy"} & set(attrs):
            raise serializers.ValidationError("Send body, audience or comment_policy.")
        return attrs


class ReactionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=REACTION_TYPES)


class CommentCreateSerializer(serializers.Serializer):
    """``reply_to_id`` is the comment answered; the server finds the thread root.
    ``parent_id`` is the older name for the same field."""

    body = serializers.CharField(max_length=8000)
    reply_to_id = serializers.UUIDField(required=False, allow_null=True)
    parent_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        target = attrs.get("reply_to_id") or attrs.get("parent_id")
        attrs["target"] = str(target) if target else None
        return attrs


class CommentEditSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=8000)


class CommentSerializer(serializers.ModelSerializer):
    """``parent_id`` is the thread root (null on a root); ``reply_to_id`` is the
    comment answered. Pass ``context={"my_reactions": {...}}`` for ``my_reaction``."""

    reply_to_author_id = serializers.SerializerMethodField()
    my_reaction = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            "id",
            "post_id",
            "author_id",
            "parent_id",
            "reply_to_id",
            "reply_to_author_id",
            "body",
            "reply_count",
            "reaction_count",
            "my_reaction",
            "created_at",
            "edited_at",
        ]

    def get_reply_to_author_id(self, obj: Comment) -> str | None:
        return str(obj.reply_to.author_id) if obj.reply_to_id and obj.reply_to else None

    def get_my_reaction(self, obj: Comment) -> str | None:
        return (self.context.get("my_reactions") or {}).get(obj.id)


class ReactorSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostReaction
        fields = ["account_id", "type", "created_at"]


class SharerSerializer(serializers.Serializer):
    """A share, shown as its sharer and the share post they wrote."""

    account_id = serializers.UUIDField(source="author_id")
    share_post_id = serializers.UUIDField(source="id")
    body = serializers.CharField()
    audience = serializers.CharField()
    created_at = serializers.DateTimeField()


class SaveSerializer(serializers.Serializer):
    item_type = serializers.ChoiceField(choices=["post", "listing", "page", "video"])
    item_id = serializers.UUIDField()


class SavedItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedItem
        fields = ["id", "item_type", "item_id", "created_at"]


class ReportSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200)
