from django.urls import include, path

from .internal_views import (
    ProfilesByAccountView,
    ProfilesByHandleView,
    ProfileSearchView,
    ProfileSnapshotView,
)

urlpatterns = [
    path("profiles/by-handle/", ProfilesByHandleView.as_view(), name="profiles-by-handle"),
    path("profiles/search/", ProfileSearchView.as_view(), name="profiles-search"),
    path("profiles/by-account/", ProfilesByAccountView.as_view(), name="profiles-by-account"),
    path(
        "profiles/<uuid:account_id>/snapshot/",
        ProfileSnapshotView.as_view(),
        name="profile-snapshot",
    ),
    path("search/", include("profiles.search_urls")),  # search's backfill (1.15)
]
