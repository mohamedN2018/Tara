from django.urls import path

from .internal_views import MembershipView, PresencePeersView

app_name = "chat_internal"

urlpatterns = [
    path(
        "conversations/<uuid:conversation_id>/members/<uuid:account_id>/",
        MembershipView.as_view(),
        name="membership",
    ),
    path(
        "accounts/<uuid:account_id>/presence-peers/",
        PresencePeersView.as_view(),
        name="presence-peers",
    ),
]
