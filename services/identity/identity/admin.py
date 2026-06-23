from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Account, RefreshToken, SecurityEvent, UserSession


@admin.register(Account)
class AccountAdmin(UserAdmin):
    ordering = ("-created_at",)
    list_display = ("email", "status", "email_verified", "is_staff", "created_at", "last_login_at")
    list_filter = ("status", "email_verified", "is_staff", "is_superuser")
    search_fields = ("email", "id")
    readonly_fields = ("id", "created_at", "updated_at", "last_login_at")
    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Status", {"fields": ("status", "email_verified", "is_active")}),
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
