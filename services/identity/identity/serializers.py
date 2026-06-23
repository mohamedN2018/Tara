from __future__ import annotations

from rest_framework import serializers

from .models import Account, UserSession


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, min_length=10, max_length=128, trim_whitespace=False
    )
    language = serializers.ChoiceField(choices=["en", "ar"], default="en")
    theme = serializers.ChoiceField(choices=["light", "dark", "system"], default="system")


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
