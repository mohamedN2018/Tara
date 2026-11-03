from django.urls import path

from .internal_views import ProfilesByHandleView, ProfileSnapshotView

urlpatterns = [
    path("profiles/by-handle/", ProfilesByHandleView.as_view(), name="profiles-by-handle"),
    path(
        "profiles/<uuid:account_id>/snapshot/",
        ProfileSnapshotView.as_view(),
        name="profile-snapshot",
    ),
]
