from __future__ import annotations

import re
from zoneinfo import available_timezones

from rest_framework import serializers

from . import push
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


class WebPushKeysSerializer(serializers.Serializer):
    p256dh = serializers.CharField(max_length=200)
    auth = serializers.CharField(max_length=100)


class WebPushSubscriptionSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=1000)
    keys = WebPushKeysSerializer()

    def validate_endpoint(self, value):
        if not push.is_allowed_endpoint(value):
            raise serializers.ValidationError("Not a known push service.")
        return value


class PushTokenSerializer(serializers.Serializer):
    """``subscription`` for web, ``token`` for native devices."""

    platform = serializers.ChoiceField(choices=["ios", "android", "web"])
    token = serializers.CharField(max_length=400, required=False)
    subscription = WebPushSubscriptionSerializer(required=False)

    def validate(self, attrs):
        field = "subscription" if attrs["platform"] == "web" else "token"
        if field not in attrs:
            raise serializers.ValidationError({field: "This field is required."})
        return attrs


class PushUnsubscribeSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=1000)


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
