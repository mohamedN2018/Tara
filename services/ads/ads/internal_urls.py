from django.urls import path

from .internal_views import FeedSlotView

urlpatterns = [
    path("ads/feed-slot/", FeedSlotView.as_view(), name="ads-feed-slot"),
]
