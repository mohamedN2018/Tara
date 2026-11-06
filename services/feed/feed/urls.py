from django.urls import path

from . import views

app_name = "feed"

urlpatterns = [
    path("feed/", views.HomeFeedView.as_view(), name="home-feed"),
    path("feed/delivery/", views.DeliveryView.as_view(), name="delivery"),
    path("feed/hide/", views.HideView.as_view(), name="hide"),
    path("feed/hide/<uuid:post_id>/", views.UnhideView.as_view(), name="unhide"),
    path("feed/snooze/", views.SnoozeView.as_view(), name="snooze"),
    path("feed/snooze/<uuid:author_id>/", views.UnsnoozeView.as_view(), name="unsnooze"),
    path("feed/snoozes/", views.SnoozeListView.as_view(), name="snoozes"),
]
