from __future__ import annotations

import re
from zoneinfo import available_timezones

from rest_framework import serializers

from . import push, registry
from .models import Notification, NotificationPreference

_TIME_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


class NotificationSerializer(serializers.ModelSerializer):
    category = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "kind",
            "category",
            "actor_id",
            "actor_count",
            "recent_actor_ids",
            "subject_ref",
            "target_ref",
            "group_key",
            "body",
            "data",
            "url",
            "resolution",
            "read_at",
            "created_at",
            "last_event_at",
        ]

    def get_category(self, obj: Notification) -> str:
        return obj.category or registry.category_of(obj.kind)

    def get_url(self, obj: Notification) -> str:
        return registry.url_for(obj)


class ReadSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        max_length=100,
    )
    all = serializers.BooleanField(required=False, default=False)


class ResolveSerializer(serializers.Serializer):
    resolution = serializers.CharField(max_length=16)


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["account_id", "prefs", "quiet_hours", "message_previews", "updated_at"]
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
    """``{kind or category: {channel: bool | null}}``, merged into what is stored.

    For example ``{"follow": {"in_app": false}}`` or ``{"social": {"push": false}}``;
    ``null`` drops that override, so the category or the default applies again.
    """

    prefs = serializers.DictField(
        child=serializers.DictField(child=serializers.BooleanField(allow_null=True)),
        required=False,
    )
    quiet_hours = serializers.JSONField(required=False)
    message_previews = serializers.BooleanField(required=False)

    def validate_prefs(self, value):
        unknown_keys = sorted(set(value) - registry.preference_keys())
        if unknown_keys:
            raise serializers.ValidationError(f"Unknown kinds: {', '.join(unknown_keys)}.")
        channels = {c for v in value.values() for c in v}
        unknown_channels = sorted(channels - set(registry.CHANNELS))
        if unknown_channels:
            raise serializers.ValidationError(f"Unknown channels: {', '.join(unknown_channels)}.")
        return value

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
