from __future__ import annotations

from rest_framework import serializers

from . import roles, services
from .models import (
    MAX_DESCRIPTION,
    MAX_NAME,
    MAX_RULE_BODY,
    MAX_RULE_TITLE,
    MAX_RULES,
    Category,
    Group,
    GroupMember,
    GroupRule,
    Privacy,
    ReportReason,
    Role,
)


class RuleInSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=MAX_RULE_TITLE)
    body = serializers.CharField(max_length=MAX_RULE_BODY, required=False, allow_blank=True)


class RuleEditSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=MAX_RULE_TITLE, required=False)
    body = serializers.CharField(max_length=MAX_RULE_BODY, required=False, allow_blank=True)


class RuleOrderSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), max_length=MAX_RULES)


class GroupCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_NAME)
    handle = serializers.CharField(max_length=30)
    description = serializers.CharField(
        max_length=MAX_DESCRIPTION, required=False, allow_blank=True, default=""
    )
    category = serializers.ChoiceField(choices=Category.values, default=Category.GENERAL)
    privacy = serializers.ChoiceField(choices=Privacy.values, default=Privacy.PUBLIC)
    membership_approval = serializers.BooleanField(default=False)
    post_approval = serializers.BooleanField(default=False)
    cover_media_id = serializers.UUIDField(required=False, allow_null=True)
    rules = RuleInSerializer(many=True, required=False, default=list)


class GroupUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_NAME, required=False)
    description = serializers.CharField(
        max_length=MAX_DESCRIPTION, required=False, allow_blank=True
    )
    category = serializers.ChoiceField(choices=Category.values, required=False)
    privacy = serializers.ChoiceField(choices=Privacy.values, required=False)
    membership_approval = serializers.BooleanField(required=False)
    post_approval = serializers.BooleanField(required=False)
    cover_media_id = serializers.UUIDField(required=False, allow_null=True)


class InviteSerializer(serializers.Serializer):
    account_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100)


class RoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.values)


class NotifySerializer(serializers.Serializer):
    notify_posts = serializers.BooleanField()


class GroupReportSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=ReportReason.values)


class RuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupRule
        fields = ["id", "title", "body", "position"]


class MembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupMember
        fields = [
            "account_id",
            "role",
            "state",
            "notify_posts",
            "invited_by",
            "joined_at",
            "created_at",
        ]


def group_data(
    group: Group,
    viewer_id: str,
    member: GroupMember | None,
    *,
    with_rules: bool = False,
) -> dict:
    """A group as one viewer sees it, with what the backend lets them do."""
    role = services.active_role(member)
    data = {
        "id": str(group.id),
        "handle": group.handle,
        "name": group.name,
        "description": group.description,
        "category": group.category,
        "privacy": group.privacy,
        "membership_approval": group.membership_approval,
        "post_approval": group.post_approval,
        "cover_media_id": str(group.cover_media_id) if group.cover_media_id else None,
        "member_count": group.member_count,
        "created_at": group.created_at.isoformat(),
        "updated_at": group.updated_at.isoformat(),
        "content_visible": services.content_visible(viewer_id, group, member),
        "viewer": {
            "role": member.role if member is not None else None,
            "state": member.state if member is not None else None,
            "notify_posts": bool(member.notify_posts) if member is not None else False,
            "can": roles.capabilities(role),
        },
    }
    if with_rules:
        data["rules"] = RuleSerializer(services.list_rules(group), many=True).data
    return data
