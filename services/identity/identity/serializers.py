from __future__ import annotations

from rest_framework import serializers

from .models import Account, UserSession

LANGUAGES = ["en", "ar"]
THEMES = ["light", "dark", "system"]
# Must match RESERVED_HANDLES in services/profile/profiles/services.py, which
# would otherwise give the account a numbered variant without saying so.
RESERVED_HANDLES = frozenset({"lookup", "id", "me", "admin", "tara"})


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, min_length=10, max_length=128, trim_whitespace=False
    )
    language = serializers.ChoiceField(choices=LANGUAGES, default="en")
    theme = serializers.ChoiceField(choices=THEMES, default="system")
    display_name = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=120
    )
    handle = serializers.RegexField(
        r"^[a-zA-Z0-9_]{3,30}$", required=False, allow_blank=True, default=""
    )

    def validate_handle(self, value: str) -> str:
        if value.lower() in RESERVED_HANDLES:
            raise serializers.ValidationError("This handle is reserved.", code="reserved_handle")
        return value


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


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
