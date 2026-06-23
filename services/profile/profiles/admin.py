from django.contrib import admin

from .models import Page, PageMember, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("handle", "display_name", "account_id", "visibility", "created_at")
    search_fields = ("handle", "account_id", "display_name")


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("handle", "name", "status", "owner_account_id", "created_at")
    search_fields = ("handle", "name")


@admin.register(PageMember)
class PageMemberAdmin(admin.ModelAdmin):
    list_display = ("page", "account_id", "role", "created_at")
