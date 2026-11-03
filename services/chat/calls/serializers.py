from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from .models import Call, CallParticipant


class StartCallSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Call.Kind.values)


class CallParticipantSerializer(serializers.ModelSerializer):
    in_room = serializers.BooleanField(read_only=True)

    class Meta:
        model = CallParticipant
        fields = ["account_id", "state", "in_room"]


class CallSerializer(serializers.ModelSerializer):
    """No room name here: it is only handed out with a join token."""

    conversation_id = serializers.UUIDField(read_only=True)
    conversation_type = serializers.SerializerMethodField()
    duration_s = serializers.SerializerMethodField()
    ring_expires_at = serializers.SerializerMethodField()
    participants = serializers.SerializerMethodField()

    class Meta:
        model = Call
        fields = [
            "id",
            "conversation_id",
            "conversation_type",
            "kind",
            "state",
            "initiator_id",
            "created_at",
            "answered_at",
            "ended_at",
            "end_reason",
            "duration_s",
            "ring_expires_at",
            "participants",
        ]

    def get_conversation_type(self, obj: Call) -> str:
        return obj.conversation.type

    def get_duration_s(self, obj: Call) -> int:
        if obj.answered_at and not obj.ended_at:
            return max(0, int((timezone.now() - obj.answered_at).total_seconds()))
        return obj.duration_s

    def get_ring_expires_at(self, obj: Call) -> str:
        return (obj.created_at + timedelta(seconds=settings.CALL_RING_TIMEOUT_SECONDS)).isoformat()

    def get_participants(self, obj: Call) -> list[dict]:
        rows = sorted(obj.participants.all(), key=lambda p: p.invited_at)
        return CallParticipantSerializer(rows, many=True).data
