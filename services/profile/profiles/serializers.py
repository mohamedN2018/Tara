from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import EmailValidator, URLValidator
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
            "searchable",
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


# Text fields, unbounded in the database (the web app allows 160 for intro).
MAX_INTRO = 500
MAX_PAGE_DESCRIPTION = 2000


class ProfileUpdateSerializer(serializers.ModelSerializer):
    intro = serializers.CharField(max_length=MAX_INTRO, required=False, allow_blank=True)

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
            "searchable",
        ]


class FieldPrivacyItemSerializer(serializers.Serializer):
    field_key = serializers.ChoiceField(choices=CONTROLLABLE_FIELDS)
    visibility = serializers.ChoiceField(
        choices=[v for v in Visibility.values if v != Visibility.CUSTOM]
    )


class FieldPrivacyBulkSerializer(serializers.Serializer):
    items = FieldPrivacyItemSerializer(many=True)


# Page contact details: known keys only, short strings, links over http(s) only.
CONTACT_LINK_KEYS = frozenset(
    {"website", "facebook", "instagram", "x", "linkedin", "youtube", "tiktok"}
)
CONTACT_PHONE_KEYS = frozenset({"phone", "whatsapp"})
CONTACT_KEYS = CONTACT_LINK_KEYS | CONTACT_PHONE_KEYS | {"email"}
MAX_CONTACT_VALUE = 200
_PHONE_CHARS = frozenset("+0123456789 -()")
_validate_link = URLValidator(schemes=["http", "https"])
_validate_email = EmailValidator()


class ContactField(serializers.DictField):
    """``{"website": "https://...", "phone": "+20 ...", "email": "..."}``.

    Blank values are dropped. A link must be http(s): ``javascript:`` and
    ``data:`` never reach a page that renders it as ``href``.
    """

    child = serializers.CharField(max_length=MAX_CONTACT_VALUE, allow_blank=True)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        unknown = sorted(set(value) - CONTACT_KEYS)
        if unknown:
            raise serializers.ValidationError(f"Unknown contact keys: {', '.join(unknown)}.")
        clean = {}
        errors = {}
        for key, text in value.items():
            text = text.strip()
            if not text:
                continue
            try:
                if key in CONTACT_LINK_KEYS:
                    _validate_link(text)
                elif key == "email":
                    _validate_email(text)
                elif not set(text) <= _PHONE_CHARS or not any(c.isdigit() for c in text):
                    raise DjangoValidationError("Enter a phone number.")
            except DjangoValidationError as exc:
                errors[key] = exc.messages
                continue
            clean[key] = text
        if errors:
            raise serializers.ValidationError(errors)
        return clean


class PageUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    category = serializers.CharField(max_length=80, required=False, allow_blank=True)
    description = serializers.CharField(
        max_length=MAX_PAGE_DESCRIPTION, required=False, allow_blank=True
    )
    contact = ContactField(required=False)
    location = serializers.CharField(max_length=160, required=False, allow_blank=True)
    # The editor's own image uploads (checked with media); null clears them.
    avatar_media_id = serializers.UUIDField(required=False, allow_null=True)
    cover_media_id = serializers.UUIDField(required=False, allow_null=True)
    # `suspended` belongs to moderation, so it can be neither set nor lifted here.
    status = serializers.ChoiceField(
        choices=[Page.Status.DRAFT, Page.Status.PUBLISHED], required=False
    )


class PageCreateSerializer(serializers.Serializer):
    handle = serializers.RegexField(r"^[a-zA-Z0-9_]{3,30}$")
    name = serializers.CharField(max_length=120)
    category = serializers.CharField(max_length=80, required=False, allow_blank=True)
    description = serializers.CharField(
        max_length=MAX_PAGE_DESCRIPTION, required=False, allow_blank=True
    )
    contact = ContactField(required=False)
    location = serializers.CharField(max_length=160, required=False, allow_blank=True)
    avatar_media_id = serializers.UUIDField(required=False, allow_null=True)
    cover_media_id = serializers.UUIDField(required=False, allow_null=True)


class PageSerializer(serializers.ModelSerializer):
    """Pass ``context={"viewer_id": ...}`` for ``my_role``, and
    ``context={"stats": page_graph.page_stats(...)}`` for the follow state and
    follower count (``None`` when graph could not answer)."""

    my_role = serializers.SerializerMethodField()
    viewer_following = serializers.SerializerMethodField()
    followers_count = serializers.SerializerMethodField()

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
            "viewer_following",
            "followers_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "owner_account_id", "created_at", "updated_at"]

    def _stats(self, obj: Page) -> dict | None:
        return (self.context.get("stats") or {}).get(str(obj.id))

    def get_viewer_following(self, obj: Page) -> bool | None:
        stats = self._stats(obj)
        return stats["following"] if stats else None

    def get_followers_count(self, obj: Page) -> int | None:
        stats = self._stats(obj)
        return stats["followers_count"] if stats else None

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
