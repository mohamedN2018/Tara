from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Account,
    AccountSuspension,
    RefreshToken,
    SecurityEvent,
    SocialIdentity,
    UserSession,
)


@admin.register(Account)
class AccountAdmin(UserAdmin):
    ordering = ("-created_at",)
    list_display = ("email", "status", "email_verified", "is_staff", "created_at", "last_login_at")
    list_filter = ("status", "email_verified", "is_staff", "is_superuser")
    search_fields = ("email", "id")
    # Status and staff flags change only through identity's audited paths
    # (suspension, the role API, ``create_admin``), never by editing here (8.4).
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "last_login_at",
        "status",
        "is_staff",
        "is_superuser",
    )
    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Status", {"fields": ("status", "email_verified", "is_active")}),
        ("Phone", {"fields": ("phone", "phone_verified_at")}),
        ("Preferences", {"fields": ("language", "theme")}),
        ("Permissions", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Timestamps", {"fields": ("created_at", "updated_at", "last_login_at")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "account", "ip_region", "created_at", "last_seen_at", "revoked_at")
    search_fields = ("account__email",)


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ("id", "account", "type", "created_at")
    list_filter = ("type",)
    search_fields = ("account__email",)


@admin.register(RefreshToken)
class RefreshTokenAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "account",
        "family_id",
        "created_at",
        "used_at",
        "revoked_at",
        "expires_at",
    )
    search_fields = ("account__email", "family_id")


@admin.register(SocialIdentity)
class SocialIdentityAdmin(admin.ModelAdmin):
    list_display = ("id", "account", "provider", "email", "created_at", "last_used_at")
    list_filter = ("provider",)
    search_fields = ("account__email", "email")
    readonly_fields = ("subject",)


@admin.register(AccountSuspension)
class AccountSuspensionAdmin(admin.ModelAdmin):
    """Read-only: suspensions are made and lifted through the admin console API."""

    list_display = ("id", "account", "source", "until", "created_at", "lifted_at")
    list_filter = ("source",)
    search_fields = ("account__email",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
