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
            "owner_id",
            "created_at",
            "updated_at",
        ]


class ManualReportSerializer(serializers.Serializer):
    # Posts, comments, listings and messages are reported through the service
    # that owns them, which checks the reporter can see the item first.
    target_type = serializers.ChoiceField(choices=["user", "page"])
    target_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=ModerationAction.Action.values)
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class AppealSerializer(serializers.ModelSerializer):
    target_type = serializers.CharField(source="case.target_type", read_only=True)
    target_id = serializers.CharField(source="case.target_id", read_only=True)

    class Meta:
        model = Appeal
        fields = [
            "id",
            "case_id",
            "target_type",
            "target_id",
            "account_id",
            "text",
            "status",
            "created_at",
        ]


class AppealCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=4000)


class AppealResolveSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[Appeal.Status.UPHELD, Appeal.Status.OVERTURNED])
