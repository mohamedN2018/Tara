from __future__ import annotations

import re
from zoneinfo import available_timezones

from rest_framework import serializers

from .models import Notification, NotificationPreference

_TIME_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


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
        required=False,
    )
    quiet_hours = serializers.JSONField(required=False)

    def validate_quiet_hours(self, value):
        """``{}`` turns quiet hours off. A window needs both ends, in 24-hour time."""
        if value == {}:
            return value
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be an object.")
        unknown = set(value) - {"start", "end", "timezone"}
        if unknown:
            raise serializers.ValidationError(f"Unknown keys: {', '.join(sorted(unknown))}.")
        start, end = value.get("start"), value.get("end")
        if not all(isinstance(t, str) and _TIME_RE.fullmatch(t) for t in (start, end)):
            raise serializers.ValidationError("start and end must be HH:MM (24-hour).")
        if start == end:
            raise serializers.ValidationError("start and end must differ.")
        timezone = value.get("timezone", "UTC")
        if timezone not in available_timezones():
            raise serializers.ValidationError("Unknown timezone.")
        return {"start": start, "end": end, "timezone": timezone}
