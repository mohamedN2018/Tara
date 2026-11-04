from __future__ import annotations

from datetime import date

from django.conf import settings
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from . import age
from .models import Account, Gender, UserSession

LANGUAGES = ["en", "ar"]
THEMES = ["light", "dark", "system"]
# Must match RESERVED_HANDLES in services/profile/profiles/services.py, which
# would otherwise give the account a numbered variant without saying so.
RESERVED_HANDLES = frozenset({"lookup", "id", "me", "admin", "tara"})


def _person_name(value: str) -> str:
    """A first or last name: trimmed, with at least one letter in any script."""
    value = " ".join(value.split())
    if not any(ch.isalpha() for ch in value):
        raise serializers.ValidationError("Enter a name with letters.", code="invalid_name")
    return value


class RegisterSerializer(serializers.Serializer):
    """Sign-up (roadmap 2.12, plan 08 §1.1).

    Field errors use the uniform envelope: ``validation_error`` with one detail
    per field, whose ``code`` says what is wrong (``password_mismatch``,
    ``age_below_minimum``, ``consent_required``, ``legal_version_mismatch``).
    The display name in profile is built from the first and last names.
    """

    first_name = serializers.CharField(max_length=40)
    last_name = serializers.CharField(max_length=40)
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, min_length=10, max_length=128, trim_whitespace=False
    )
    password_confirm = serializers.CharField(write_only=True, max_length=128, trim_whitespace=False)
    date_of_birth = serializers.DateField()
    gender = serializers.ChoiceField(
        choices=Gender.choices, required=False, allow_blank=True, default=""
    )
    gender_custom = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=40
    )
    # Missing counts as not accepted: the check below says so in one code.
    accept_terms = serializers.BooleanField(required=False, default=False)
    terms_version = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=40
    )
    privacy_version = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=40
    )
    language = serializers.ChoiceField(choices=LANGUAGES, default="en")
    theme = serializers.ChoiceField(choices=THEMES, default="system")
    handle = serializers.RegexField(
        r"^[a-zA-Z0-9_]{3,30}$", required=False, allow_blank=True, default=""
    )

    def validate_first_name(self, value: str) -> str:
        return _person_name(value)

    def validate_last_name(self, value: str) -> str:
        return _person_name(value)

    def validate_handle(self, value: str) -> str:
        if value.lower() in RESERVED_HANDLES:
            raise serializers.ValidationError("This handle is reserved.", code="reserved_handle")
        return value

    def validate_date_of_birth(self, value: date) -> date:
        today = age.today()
        if value > today or age.age_on(value, today) > age.MAX_AGE:
            raise serializers.ValidationError("Enter a real date of birth.", code="invalid_date")
        if age.age_on(value, today) < settings.REGISTRATION_MIN_AGE:
            raise serializers.ValidationError(
                "You are too young to create an account.", code="age_below_minimum"
            )
        return value

    def validate_accept_terms(self, value: bool) -> bool:
        if value is not True:
            raise serializers.ValidationError(
                "Accept the terms and the privacy policy to continue.", code="consent_required"
            )
        return value

    def validate(self, attrs: dict) -> dict:
        # ErrorDetail keeps each field's code; a nested ValidationError would not.
        errors: dict[str, list[ErrorDetail]] = {}
        if attrs["password"] != attrs["password_confirm"]:
            errors["password_confirm"] = [
                ErrorDetail("The passwords do not match.", code="password_mismatch")
            ]
        for field, current in (
            ("terms_version", settings.LEGAL_TERMS_VERSION),
            ("privacy_version", settings.LEGAL_PRIVACY_VERSION),
        ):
            if attrs[field] != current:
                errors[field] = [
                    ErrorDetail(
                        "The legal text has changed. Reload the page and accept it again.",
                        code="legal_version_mismatch",
                    )
                ]
        attrs["gender_custom"] = " ".join(attrs["gender_custom"].split())
        if attrs["gender"] == Gender.CUSTOM and not attrs["gender_custom"]:
            errors["gender_custom"] = [
                ErrorDetail("Describe your gender, or pick another option.", code="required")
            ]
        elif attrs["gender"] != Gender.CUSTOM:
            attrs["gender_custom"] = ""
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()


class LoginSerializer(serializers.Serializer):
    # 5.6: ``identifier`` is an email or a username. ``email`` stays for older clients.
    identifier = serializers.CharField(required=False, allow_blank=True, max_length=254)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    # Unticked "Remember me": the refresh cookie lasts until the browser closes.
    remember = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        identifier = attrs.get("identifier") or attrs.get("email") or ""
        if not identifier:
            raise serializers.ValidationError(
                {"identifier": ["This field is required."]}, code="required"
            )
        attrs["identifier"] = identifier
        return attrs


class RefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(required=False, allow_blank=True)


class VerifyEmailSerializer(serializers.Serializer):
    token = serializers.CharField()


class PasswordForgotSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(
        write_only=True, min_length=10, max_length=128, trim_whitespace=False
    )


class TokenResponseSerializer(serializers.Serializer):
    """Documents the auth response body (mobile reads refresh_token; web uses cookie)."""

    access_token = serializers.CharField()
    token_type = serializers.CharField(default="Bearer")
    expires_in = serializers.IntegerField()
    refresh_token = serializers.CharField()


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = [
            "id",
            "email",
            "email_verified",
            "status",
            "language",
            "theme",
            "created_at",
            "last_login_at",
        ]
        read_only_fields = fields


class AccountUpdateSerializer(serializers.ModelSerializer):
    # The model columns are free text; only these values mean anything to clients.
    language = serializers.ChoiceField(choices=LANGUAGES, required=False)
    theme = serializers.ChoiceField(choices=THEMES, required=False)

    class Meta:
        model = Account
        fields = ["language", "theme"]


class SessionSerializer(serializers.ModelSerializer):
    platform = serializers.CharField(source="device.platform", default="web", read_only=True)
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = [
            "id",
            "ip_region",
            "user_agent",
            "platform",
            "created_at",
            "last_seen_at",
            "is_current",
        ]

    def get_is_current(self, obj: UserSession) -> bool:
        return str(obj.id) == self.context.get("current_session_id")


# ---- Account security -------------------------------------------------------


class GoogleSignInSerializer(serializers.Serializer):
    credential = serializers.CharField(max_length=4096)
    # Only used when the sign-in creates the account.
    language = serializers.ChoiceField(choices=LANGUAGES, default="en")
    theme = serializers.ChoiceField(choices=THEMES, default="system")


class GoogleLinkSerializer(serializers.Serializer):
    credential = serializers.CharField(max_length=4096)
    # Required when the account has a password (checked in account_security).
    password = serializers.CharField(
        write_only=True, max_length=128, trim_whitespace=False, required=False, allow_blank=True
    )


class GoogleUnlinkSerializer(serializers.Serializer):
    password = serializers.CharField(
        write_only=True, max_length=128, trim_whitespace=False, required=False, allow_blank=True
    )


class ChangePasswordSerializer(serializers.Serializer):
    # Blank is allowed so a password-less (Google-only) account gets "no_password".
    current_password = serializers.CharField(
        write_only=True, max_length=128, trim_whitespace=False, allow_blank=True
    )
    new_password = serializers.CharField(
        write_only=True, min_length=10, max_length=128, trim_whitespace=False
    )


class ChangeEmailSerializer(serializers.Serializer):
    new_email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, max_length=128, trim_whitespace=False, allow_blank=True
    )


class ConfirmEmailChangeSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=128)


class GoogleLinkStatusSerializer(serializers.Serializer):
    linked = serializers.BooleanField()
    email = serializers.EmailField(allow_null=True)
    linked_at = serializers.DateTimeField(allow_null=True)


class SecurityOverviewSerializer(serializers.Serializer):
    """Documents GET /me/security/ (built by account_security.security_overview)."""

    email = serializers.EmailField()
    email_verified = serializers.BooleanField()
    has_password = serializers.BooleanField()
    pending_email = serializers.EmailField(allow_null=True)
    google = GoogleLinkStatusSerializer()
    phone = serializers.CharField(allow_null=True)
    phone_verified = serializers.BooleanField()
    phone_verified_at = serializers.DateTimeField(allow_null=True)
