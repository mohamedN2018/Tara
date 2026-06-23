from __future__ import annotations

from rest_framework import serializers

from .models import FollowRelation, Friendship


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


class FollowCreateSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(
        choices=FollowRelation.TargetType.values, default=FollowRelation.TargetType.USER
    )
