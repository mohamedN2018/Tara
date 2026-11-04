from __future__ import annotations

import uuid

from rest_framework import serializers

from .models import AuditEntry, FeatureFlag


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
    role = serializers.ChoiceField(choices=["admin", "moderator", "ad_reviewer", "analyst"])


class CapabilityChangeSerializer(serializers.Serializer):
    """One matrix cell. Identity validates role and key against the registry."""

    role = serializers.CharField(max_length=32)
    capability = serializers.CharField(max_length=80)
    state = serializers.ChoiceField(choices=["grant", "revoke", "default"])


class CapabilityMatrixUpdateSerializer(serializers.Serializer):
    changes = CapabilityChangeSerializer(many=True, allow_empty=False, max_length=200)


class AuditFilterSerializer(serializers.Serializer):
    """Query filters for the audit list and export (bad input is a 400, not a 500)."""

    actor = serializers.CharField(required=False, max_length=36)
    action = serializers.CharField(required=False, max_length=64)
    target_type = serializers.CharField(required=False, max_length=32)
    target_id = serializers.CharField(required=False, max_length=64)
    since = serializers.DateTimeField(required=False)
    until = serializers.DateTimeField(required=False)

    def validate_actor(self, value: str) -> str:
        if value == "system":
            return value
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise serializers.ValidationError("An account id or 'system'.") from exc

    def validate(self, attrs: dict) -> dict:
        if attrs.get("since") and attrs.get("until") and attrs["since"] >= attrs["until"]:
            raise serializers.ValidationError({"until": "Must be after 'since'."})
        return attrs


class AuditEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEntry
        fields = [
            "id",
            "occurred_at",
            "actor_kind",
            "actor_id",
            "actor_name",
            "action",
            "target_type",
            "target_id",
            "request_id",
            "detail",
            "reason",
        ]


# ---- user management console (8.6) -------------------------------------------


class UserSearchSerializer(serializers.Serializer):
    q = serializers.CharField(min_length=2, max_length=254, trim_whitespace=True)
    field = serializers.ChoiceField(
        choices=["auto", "email", "handle", "name", "id"], default="auto"
    )
    cursor = serializers.CharField(required=False, max_length=500)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=50, default=20)


class ReasonSerializer(serializers.Serializer):
    """A staff member's own words for why: required for every sensitive step."""

    reason = serializers.CharField(min_length=5, max_length=500, trim_whitespace=True)


class SuspendSerializer(ReasonSerializer):
    until = serializers.DateTimeField(required=False, allow_null=True, default=None)

    def validate_until(self, value):
        from django.utils import timezone

        if value is not None and value <= timezone.now():
            raise serializers.ValidationError("Must be in the future.")
        return value


class SystemNoticeSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    body = serializers.CharField(read_only=True)
    recipient_ids = serializers.ListField(child=serializers.CharField(), read_only=True)
    recipient_count = serializers.IntegerField(read_only=True)
    created_by = serializers.UUIDField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class SystemNoticeWriteSerializer(serializers.Serializer):
    recipient_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=50
    )
    body = serializers.CharField(max_length=300)
