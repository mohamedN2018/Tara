from django.urls import path

from . import views

app_name = "reels"

urlpatterns = [
    path("reels/", views.ReelListCreateView.as_view(), name="reel-list"),
    path("reels/eligibility/", views.ReelEligibilityView.as_view(), name="reel-eligibility"),
    path("reels/batch/", views.ReelBatchView.as_view(), name="reel-batch"),
    path("reels/<uuid:reel_id>/", views.ReelDetailView.as_view(), name="reel-detail"),
    path("reels/<uuid:reel_id>/view/", views.ReelViewView.as_view(), name="reel-view"),
    path("reels/<uuid:reel_id>/hide/", views.ReelHideView.as_view(), name="reel-hide"),
]
