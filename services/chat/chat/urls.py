from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("conversations/", views.ConversationsView.as_view(), name="conversations"),
    path(
        "conversations/<uuid:conversation_id>/",
        views.ConversationDetailView.as_view(),
        name="conversation",
    ),
    path(
        "conversations/<uuid:conversation_id>/members/",
        views.ConversationMembersView.as_view(),
        name="members",
    ),
    path(
        "conversations/<uuid:conversation_id>/members/<uuid:account_id>/",
        views.ConversationMemberView.as_view(),
        name="member",
    ),
    path(
        "conversations/<uuid:conversation_id>/messages/",
        views.ConversationMessagesView.as_view(),
        name="messages",
    ),
    path(
        "conversations/<uuid:conversation_id>/voice-messages/",
        views.VoiceMessagesView.as_view(),
        name="voice-messages",
    ),
    path(
        "conversations/<uuid:conversation_id>/read/",
        views.ConversationReadView.as_view(),
        name="read",
    ),
    path(
        "conversations/<uuid:conversation_id>/mute/",
        views.ConversationMuteView.as_view(),
        name="mute",
    ),
    path(
        "conversations/<uuid:conversation_id>/pin/", views.ConversationPinView.as_view(), name="pin"
    ),
    path(
        "messages/<uuid:message_id>/reactions/",
        views.MessageReactionView.as_view(),
        name="message-reactions",
    ),
]
