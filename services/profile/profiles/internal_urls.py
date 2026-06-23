from django.urls import path

from .internal_views import ProfileSnapshotView

urlpatterns = [
    path(
        "profiles/<uuid:account_id>/snapshot/",
        ProfileSnapshotView.as_view(),
        name="profile-snapshot",
    ),
]
