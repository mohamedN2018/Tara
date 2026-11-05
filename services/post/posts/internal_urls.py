from django.urls import include, path

from .internal_views import PostVisibilityView

urlpatterns = [
    path(
        "posts/<uuid:post_id>/visibility/",
        PostVisibilityView.as_view(),
        name="internal-post-visibility",
    ),
    path("search/", include("posts.search_urls")),  # search v2 (1.15)
    path("intel/", include("posts.intel_export")),  # feed intel backfill (WP 3.2)
]
