from __future__ import annotations

from rest_framework import serializers

from .models import FeatureFlag


class FeatureFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlag
        fields = ["key", "enabled", "rollout_pct", "targeting", "description", "updated_at"]


class FeatureFlagWriteSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(default=False)
    rollout_pct = serializers.IntegerField(min_value=0, max_value=100, default=0)
    description = serializers.CharField(
        max_length=300, required=False, allow_blank=True, default=""
    )


class RoleSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
    role = serializers.ChoiceField(
        choices=["admin", "moderator", "analyst", "advertiser", "editor"]
    )
