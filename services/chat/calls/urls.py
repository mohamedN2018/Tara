from django.urls import path

from . import views

app_name = "calls"

urlpatterns = [
    path("calls/config/", views.CallConfigView.as_view(), name="config"),
    path(
        "conversations/<uuid:conversation_id>/calls/",
        views.ConversationCallsView.as_view(),
        name="start",
    ),
    path(
        "conversations/<uuid:conversation_id>/calls/active/",
        views.ActiveCallView.as_view(),
        name="active",
    ),
    path("calls/<uuid:call_id>/join/", views.CallJoinView.as_view(), name="join"),
    path("calls/<uuid:call_id>/decline/", views.CallDeclineView.as_view(), name="decline"),
    path("calls/<uuid:call_id>/end/", views.CallEndView.as_view(), name="end"),
]
