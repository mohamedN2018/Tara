from __future__ import annotations

from rest_framework import serializers

from .models import Appeal, ModerationAction, ModerationCase, Report


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = ["id", "reporter_id", "target_type", "target_id", "reason", "created_at"]


class CaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModerationCase
        fields = [
            "id",
            "target_type",
            "target_id",
            "severity",
            "state",
            "report_count",
            "assigned_to",
            "created_at",
            "updated_at",
        ]


class ManualReportSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(
        choices=["post", "comment", "message", "listing", "page", "user"]
    )
    target_id = serializers.CharField(max_length=64)
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=ModerationAction.Action.values)
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class AppealCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=4000)


class AppealResolveSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[Appeal.Status.UPHELD, Appeal.Status.OVERTURNED])
