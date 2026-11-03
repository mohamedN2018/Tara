from django.urls import path

from .internal_views import PostVisibilityView

urlpatterns = [
    path(
        "posts/<uuid:post_id>/visibility/",
        PostVisibilityView.as_view(),
        name="internal-post-visibility",
    ),
]
