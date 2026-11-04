from __future__ import annotations

from rest_framework import serializers

from .models import DismissedSuggestion, FollowRelation, Friendship, RelationshipSettings


class FriendRequestCreateSerializer(serializers.Serializer):
    to_user_id = serializers.UUIDField()


class FriendshipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Friendship
        fields = [
            "id",
            "account_low_id",
            "account_high_id",
            "status",
            "requested_by",
            "created_at",
            "accepted_at",
        ]


class RelationshipSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = RelationshipSettings
        fields = [
            "friends_list_visibility",
            "follow_lists_visibility",
            "counts_visibility",
            "friend_requests_from",
        ]


class DismissSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(
        choices=DismissedSuggestion.TargetType.values,
        default=DismissedSuggestion.TargetType.USER,
    )


class FollowCreateSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(
        choices=FollowRelation.TargetType.values, default=FollowRelation.TargetType.USER
    )
