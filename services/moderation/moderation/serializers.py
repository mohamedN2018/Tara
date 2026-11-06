from __future__ import annotations

from rest_framework import serializers

from .models import Appeal, ModerationAction, ModerationCase, Report


class ReportSerializer(serializers.ModelSerializer):
    # A system-sourced report (WP 7.4) has no reporter: the reserved id stays inside.
    reporter_id = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            "id",
            "reporter_id",
            "source",
            "target_type",
            "target_id",
            "reason",
            "evidence",
            "created_at",
        ]

    def get_reporter_id(self, obj) -> str | None:
        if obj.source == Report.Source.SYSTEM:
            return None
        return str(obj.reporter_id)


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
            "system_signal",
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


class MyCaseSerializer(serializers.ModelSerializer):
    """A decision about the member's own content or account (``account_status.my_cases``).

    ``reason`` is what the moderator chose to share with the owner. Never the
    reporters, the report count, the assignee or the moderator.
    """

    decision = serializers.CharField(read_only=True)
    reason = serializers.CharField(source="decision_reason", read_only=True)
    decided_at = serializers.DateTimeField(read_only=True)
    appeal_status = serializers.CharField(read_only=True, allow_null=True)
    appealed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    can_appeal = serializers.SerializerMethodField()

    class Meta:
        model = ModerationCase
        fields = [
            "id",
            "target_type",
            "target_id",
            "decision",
            "reason",
            "decided_at",
            "appeal_status",
            "appealed_at",
            "can_appeal",
        ]

    def get_can_appeal(self, obj) -> bool:
        return obj.appeal_status is None


class MyReportSerializer(serializers.ModelSerializer):
    """One report the member filed, with the coarse state of the case it joined."""

    state = serializers.SerializerMethodField()
    outcome = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = ["id", "target_type", "target_id", "reason", "created_at", "state", "outcome"]

    def _status(self, obj) -> tuple:
        return self.context.get("outcomes", {}).get(obj.id, ("open", None))

    def get_state(self, obj) -> str:
        return self._status(obj)[0]

    def get_outcome(self, obj) -> str | None:
        return self._status(obj)[1]
