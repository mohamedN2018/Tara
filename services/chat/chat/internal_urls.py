from django.urls import path

from .internal_views import MembershipView

app_name = "chat_internal"

urlpatterns = [
    path(
        "conversations/<uuid:conversation_id>/members/<uuid:account_id>/",
        MembershipView.as_view(),
        name="membership",
    ),
]
