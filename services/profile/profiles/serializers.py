from __future__ import annotations

from rest_framework import serializers

from .models import (
    CONTROLLABLE_FIELDS,
    Page,
    PageMember,
    PageRole,
    UserEducation,
    UserLink,
    UserProfile,
    UserWorkExperience,
    Visibility,
)


class LinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserLink
        fields = ["id", "label", "url", "position"]


class EducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserEducation
        fields = ["id", "school", "degree", "field", "start_year", "end_year"]


class WorkSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserWorkExperience
        fields = ["id", "company", "title", "start_date", "end_date", "is_current"]


class MyProfileSerializer(serializers.ModelSerializer):
    links = LinkSerializer(many=True, read_only=True)
    education = EducationSerializer(many=True, read_only=True)
    work = WorkSerializer(many=True, read_only=True)

    class Meta:
        model = UserProfile
        fields = [
            "id",
            "account_id",
            "handle",
            "display_name",
            "bio",
            "intro",
            "city",
            "country",
            "avatar_media_id",
            "cover_media_id",
            "visibility",
            "completion_pct",
            "links",
            "education",
            "work",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "account_id",
            "handle",
            "completion_pct",
            "created_at",
            "updated_at",
        ]


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = [
            "display_name",
            "bio",
            "intro",
            "city",
            "country",
            "avatar_media_id",
            "cover_media_id",
            "visibility",
        ]


class FieldPrivacyItemSerializer(serializers.Serializer):
    field_key = serializers.ChoiceField(choices=CONTROLLABLE_FIELDS)
    visibility = serializers.ChoiceField(
        choices=[v for v in Visibility.values if v != Visibility.CUSTOM]
    )


class FieldPrivacyBulkSerializer(serializers.Serializer):
    items = FieldPrivacyItemSerializer(many=True)


class PageUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    category = serializers.CharField(max_length=80, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    contact = serializers.DictField(required=False)
    location = serializers.CharField(max_length=160, required=False, allow_blank=True)
    # `suspended` belongs to moderation, so it can be neither set nor lifted here.
    status = serializers.ChoiceField(
        choices=[Page.Status.DRAFT, Page.Status.PUBLISHED], required=False
    )


class PageCreateSerializer(serializers.Serializer):
    handle = serializers.RegexField(r"^[a-zA-Z0-9_]{3,30}$")
    name = serializers.CharField(max_length=120)
    category = serializers.CharField(max_length=80, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    contact = serializers.DictField(required=False)
    location = serializers.CharField(max_length=160, required=False, allow_blank=True)


class PageSerializer(serializers.ModelSerializer):
    """Pass ``context={"viewer_id": ...}`` for ``my_role``."""

    my_role = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = [
            "id",
            "handle",
            "name",
            "category",
            "description",
            "avatar_media_id",
            "cover_media_id",
            "contact",
            "location",
            "status",
            "owner_account_id",
            "my_role",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "owner_account_id", "created_at", "updated_at"]

    def get_my_role(self, obj: Page) -> str | None:
        viewer = str(self.context.get("viewer_id"))
        mine = getattr(obj, "viewer_memberships", None)
        members = mine if mine is not None else obj.members.filter(account_id=viewer)
        return next((m.role for m in members if str(m.account_id) == viewer), None)


class PageMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = PageMember
        fields = ["id", "account_id", "role", "invited_by", "created_at"]
        read_only_fields = ["id", "invited_by", "created_at"]


class MemberAddSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=[r for r in PageRole.values if r != PageRole.OWNER])


class MemberRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=[r for r in PageRole.values if r != PageRole.OWNER])


class ProfileLookupSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), max_length=100)
