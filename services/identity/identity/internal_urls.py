from django.urls import path

from tara_common.stats import InternalStatsView

from .internal_views import (
    AccountLookupView,
    AccountOverviewView,
    AccountPersonalDataView,
    AccountRolesView,
    AccountSearchView,
    AccountSignOutView,
    AccountSummariesView,
    AccountSuspensionView,
    AccountVerificationView,
    CapabilityMatrixView,
    RoleHoldersView,
)
from .stats import COUNTERS

urlpatterns = [
    path("accounts/lookup/", AccountLookupView.as_view(), name="internal-account-lookup"),
    path("role-holders/", RoleHoldersView.as_view(), name="internal-role-holders"),
    path(
        "accounts/<uuid:account_id>/roles/",
        AccountRolesView.as_view(),
        name="internal-account-roles",
    ),
    path("capabilities/", CapabilityMatrixView.as_view(), name="internal-capabilities"),
    # Admin's user management console (8.6) and suspensions (8.4).
    path("accounts/search/", AccountSearchView.as_view(), name="internal-account-search"),
    path("accounts/summaries/", AccountSummariesView.as_view(), name="internal-account-summaries"),
    path(
        "accounts/<uuid:account_id>/overview/",
        AccountOverviewView.as_view(),
        name="internal-account-overview",
    ),
    path(
        "accounts/<uuid:account_id>/personal/",
        AccountPersonalDataView.as_view(),
        name="internal-account-personal",
    ),
    path(
        "accounts/<uuid:account_id>/suspension/",
        AccountSuspensionView.as_view(),
        name="internal-account-suspension",
    ),
    path(
        "accounts/<uuid:account_id>/sign-out/",
        AccountSignOutView.as_view(),
        name="internal-account-sign-out",
    ),
    path(
        "accounts/<uuid:account_id>/verification/",
        AccountVerificationView.as_view(),
        name="internal-account-verification",
    ),
    path("stats/", InternalStatsView.as_view(counters=COUNTERS), name="internal-stats"),
]
