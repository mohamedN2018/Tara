from __future__ import annotations

from rest_framework import serializers

from .models import Notification, NotificationPreference


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "kind",
            "actor_id",
            "subject_ref",
            "group_key",
            "body",
            "read_at",
            "created_at",
        ]


class ReadSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    all = serializers.BooleanField(required=False, default=False)


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["account_id", "prefs", "quiet_hours", "updated_at"]
        read_only_fields = ["account_id", "updated_at"]


class PushTokenSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=["ios", "android", "web"])
    token = serializers.CharField(max_length=400)


class PreferenceUpdateSerializer(serializers.Serializer):
    """``{kind: {channel: bool}}``, for example ``{"follow": {"in_app": false}}``."""

    prefs = serializers.DictField(
        child=serializers.DictField(child=serializers.BooleanField()),
    )
