from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("notifications/", views.NotificationsView.as_view(), name="list"),
    path("notifications/unread-count/", views.UnreadCountView.as_view(), name="unread-count"),
    path("notifications/read/", views.ReadView.as_view(), name="read"),
    path("notifications/preferences/", views.PreferencesView.as_view(), name="preferences"),
    path("notifications/kinds/", views.KindsView.as_view(), name="kinds"),
    path("notifications/<uuid:pk>/", views.NotificationDetailView.as_view(), name="detail"),
    path("notifications/<uuid:pk>/resolve/", views.ResolveView.as_view(), name="resolve"),
    path("devices/push-token/", views.PushTokenView.as_view(), name="push-token"),
    path("devices/push-config/", views.PushConfigView.as_view(), name="push-config"),
]
