from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("conversations/", views.ConversationsView.as_view(), name="conversations"),
    path("conversations/unread/", views.UnreadView.as_view(), name="unread"),
    path("conversations/delivered/", views.DeliveredView.as_view(), name="delivered"),
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
        "conversations/<uuid:conversation_id>/archive/",
        views.ConversationArchiveView.as_view(),
        name="archive",
    ),
    path(
        "conversations/<uuid:conversation_id>/clear/",
        views.ConversationClearView.as_view(),
        name="clear",
    ),
    path(
        "conversations/<uuid:conversation_id>/search/",
        views.ConversationSearchView.as_view(),
        name="conversation-search",
    ),
    path(
        "conversations/<uuid:conversation_id>/media/",
        views.ConversationMediaView.as_view(),
        name="shared-media",
    ),
    path("messages/search/", views.MessageSearchView.as_view(), name="message-search"),
    path("messages/<uuid:message_id>/", views.MessageDetailView.as_view(), name="message"),
    path(
        "messages/<uuid:message_id>/forward/",
        views.MessageForwardView.as_view(),
        name="message-forward",
    ),
    path(
        "messages/<uuid:message_id>/attachments/<uuid:media_id>/",
        views.MessageAttachmentView.as_view(),
        name="message-attachment",
    ),
    path(
        "messages/<uuid:message_id>/reactions/",
        views.MessageReactionView.as_view(),
        name="message-reactions",
    ),
]
