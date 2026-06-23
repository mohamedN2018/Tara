from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("notifications/", views.NotificationsView.as_view(), name="list"),
    path("notifications/unread-count/", views.UnreadCountView.as_view(), name="unread-count"),
    path("notifications/read/", views.ReadView.as_view(), name="read"),
    path("notifications/preferences/", views.PreferencesView.as_view(), name="preferences"),
    path("devices/push-token/", views.PushTokenView.as_view(), name="push-token"),
]
