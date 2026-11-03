from __future__ import annotations

from rest_framework import serializers

from . import services
from .models import (
    MAX_CAPACITY,
    MAX_DESCRIPTION,
    MAX_LOCATION,
    MAX_TITLE,
    MAX_URL,
    Gathering,
    GatheringInvite,
    GatheringRSVP,
    ReportReason,
    RSVPStatus,
)


class GatheringCreateSerializer(serializers.Serializer):
    """Also the edit serializer, with ``partial=True`` (no defaults applied then)."""

    title = serializers.CharField(max_length=MAX_TITLE)
    description = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=MAX_DESCRIPTION
    )
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    timezone = serializers.CharField(max_length=64, required=False, default="UTC")
    location_type = serializers.ChoiceField(
        choices=Gathering.LocationType.values, default=Gathering.LocationType.PLACE
    )
    location = serializers.CharField(
        max_length=MAX_LOCATION, required=False, allow_blank=True, default=""
    )
    online_url = serializers.CharField(
        max_length=MAX_URL, required=False, allow_blank=True, default="", trim_whitespace=True
    )
    cover_media_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    audience = serializers.ChoiceField(
        choices=Gathering.Audience.values, default=Gathering.Audience.PUBLIC
    )
    capacity = serializers.IntegerField(
        min_value=1, max_value=MAX_CAPACITY, required=False, allow_null=True, default=None
    )


class GatheringSerializer(serializers.ModelSerializer):
    """An event as the viewer sees it. ``status`` is ``ended`` as soon as the end
    passes; ``my_rsvp`` and ``invited`` are the viewer's own state."""

    status = serializers.SerializerMethodField()
    is_host = serializers.SerializerMethodField()
    my_rsvp = serializers.SerializerMethodField()
    invited = serializers.SerializerMethodField()
    spots_left = serializers.SerializerMethodField()

    class Meta:
        model = Gathering
        fields = [
            "id",
            "host_id",
            "host_type",
            "page_id",
            "title",
            "description",
            "starts_at",
            "ends_at",
            "timezone",
            "location_type",
            "location",
            "online_url",
            "cover_media_id",
            "audience",
            "capacity",
            "going_count",
            "interested_count",
            "spots_left",
            "status",
            "cancelled_at",
            "is_host",
            "my_rsvp",
            "invited",
            "created_at",
            "updated_at",
        ]

    def _state(self) -> dict:
        return self.context.get("viewer_state") or {"rsvp": {}, "invited": set()}

    def get_status(self, obj: Gathering) -> str:
        return services.effective_status(obj)

    def get_is_host(self, obj: Gathering) -> bool:
        return str(obj.host_id) == str(self.context.get("viewer_id"))

    def get_my_rsvp(self, obj: Gathering) -> str | None:
        return self._state()["rsvp"].get(obj.id)

    def get_invited(self, obj: Gathering) -> bool:
        return obj.id in self._state()["invited"]

    def get_spots_left(self, obj: Gathering) -> int | None:
        if obj.capacity is None:
            return None
        return max(0, obj.capacity - obj.going_count)


class RSVPSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=RSVPStatus.values)


class AttendeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GatheringRSVP
        fields = ["account_id", "status", "updated_at"]


class InviteeSerializer(serializers.ModelSerializer):
    account_id = serializers.UUIDField(source="invitee_id")

    class Meta:
        model = GatheringInvite
        fields = ["account_id", "created_at"]


class InviteSerializer(serializers.Serializer):
    account_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=services.MAX_INVITES_PER_CALL
    )


class GatheringReportSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=ReportReason.values)
