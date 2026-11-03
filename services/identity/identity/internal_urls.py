from django.urls import path

from tara_common.stats import InternalStatsView

from .internal_views import (
    AccountLookupView,
    AccountRolesView,
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
    path("stats/", InternalStatsView.as_view(counters=COUNTERS), name="internal-stats"),
]
