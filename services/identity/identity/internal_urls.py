from django.urls import path

from .internal_views import AccountLookupView, AccountRolesView, RoleHoldersView

urlpatterns = [
    path("accounts/lookup/", AccountLookupView.as_view(), name="internal-account-lookup"),
    path("role-holders/", RoleHoldersView.as_view(), name="internal-role-holders"),
    path(
        "accounts/<uuid:account_id>/roles/",
        AccountRolesView.as_view(),
        name="internal-account-roles",
    ),
]
