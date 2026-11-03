"""Chat HTTP API: conversations, messages, voice notes, reactions, receipts,
inbox state (archive, clear, mute, pin), message lifecycle (edit, delete,
forward), search, shared media and attachment URLs."""

from __future__ import annotations

from datetime import timedelta

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from . import services
from .models import Message
from .serializers import (
    ArchiveSerializer,
    ConversationSerializer,
    DMCreateSerializer,
    ForwardSerializer,
    GroupCreateSerializer,
    GroupUpdateSerializer,
    MemberRoleSerializer,
    MembersAddSerializer,
    MessageCreateSerializer,
    MessageEditSerializer,
    MessageSerializer,
    MuteSerializer,
    PinSerializer,
    ReactionSerializer,
    ReadSerializer,
    SharedMediaSerializer,
    VoiceMessageSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


def _paginate(request, queryset, serializer_cls, context=None):
    paginator = CursorPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(
        serializer_cls(page, many=True, context=context or {}).data
    )


def _conversation_data(request: Request, conversation_id) -> dict:
    conversation = services.get_conversation(_me(request), conversation_id)
    return ConversationSerializer(conversation, context={"viewer_id": _me(request)}).data


class ConversationsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ConversationSerializer(many=True)}, tags=["chat"])
    def get(self, request: Request) -> Response:
        archived = request.query_params.get("archived", "").lower() in ("1", "true", "yes")
        return _paginate(
            request,
            services.list_conversations(_me(request), archived=archived),
            ConversationSerializer,
            {"viewer_id": _me(request)},
        )

    @extend_schema(responses={201: ConversationSerializer}, tags=["chat"])
    def post(self, request: Request) -> Response:
        conv_type = request.data.get("type", "dm")
        if conv_type == "group":
            serializer = GroupCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            conversation = services.create_group(
                _me(request),
                [str(m) for m in serializer.validated_data["member_ids"]],
                serializer.validated_data["title"],
            )
        else:
            serializer = DMCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            conversation = services.create_or_get_dm(
                _me(request), str(serializer.validated_data["other_id"])
            )
        return data_response(
            _conversation_data(request, conversation.id), status=status.HTTP_201_CREATED
        )


class ConversationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ConversationSerializer}, tags=["chat"])
    def get(self, request: Request, conversation_id: str) -> Response:
        return data_response(_conversation_data(request, conversation_id))

    @extend_schema(
        request=GroupUpdateSerializer, responses={200: ConversationSerializer}, tags=["chat"]
    )
    def patch(self, request: Request, conversation_id: str) -> Response:
        serializer = GroupUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.rename_group(_me(request), conversation_id, serializer.validated_data["title"])
        return data_response(_conversation_data(request, conversation_id))


class ConversationMembersView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=MembersAddSerializer, responses={201: ConversationSerializer}, tags=["chat"]
    )
    def post(self, request: Request, conversation_id: str) -> Response:
        serializer = MembersAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_members(
            _me(request),
            conversation_id,
            [str(a) for a in serializer.validated_data["account_ids"]],
        )
        return data_response(
            _conversation_data(request, conversation_id), status=status.HTTP_201_CREATED
        )


class ConversationMemberView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=MemberRoleSerializer, responses={200: ConversationSerializer}, tags=["chat"]
    )
    def patch(self, request: Request, conversation_id: str, account_id: str) -> Response:
        serializer = MemberRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_member_role(
            _me(request), conversation_id, account_id, serializer.validated_data["role"]
        )
        return data_response(_conversation_data(request, conversation_id))

    @extend_schema(responses={204: None}, tags=["chat"])
    def delete(self, request: Request, conversation_id: str, account_id: str) -> Response:
        services.remove_member(_me(request), conversation_id, account_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConversationMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MessageSerializer(many=True)}, tags=["chat"])
    def get(self, request: Request, conversation_id: str) -> Response:
        return _paginate(
            request, services.list_messages(_me(request), conversation_id), MessageSerializer
        )

    @extend_schema(
        request=MessageCreateSerializer, responses={201: MessageSerializer}, tags=["chat"]
    )
    def post(self, request: Request, conversation_id: str) -> Response:
        serializer = MessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        message = services.send_message(
            _me(request),
            conversation_id,
            body=v["body"],
            message_type=v["type"],
            reply_to_id=str(v["reply_to_id"]) if v.get("reply_to_id") else None,
            attachments=[
                {
                    "media_id": str(a["media_id"]),
                    "kind": a.get("kind", "file"),
                    "duration_ms": a.get("duration_ms"),
                    "file_name": a.get("file_name", ""),
                }
                for a in v["attachments"]
            ],
        )
        return data_response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class VoiceMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=VoiceMessageSerializer, responses={201: MessageSerializer}, tags=["chat"]
    )
    def post(self, request: Request, conversation_id: str) -> Response:
        serializer = VoiceMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = services.send_message(
            _me(request),
            conversation_id,
            message_type=Message.Type.VOICE,
            attachments=[
                {
                    "media_id": str(serializer.validated_data["media_id"]),
                    "kind": "voice",
                    "duration_ms": serializer.validated_data["duration_ms"],
                }
            ],
        )
        return data_response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class MessageReactionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReactionSerializer, responses={200: None}, tags=["chat"])
    def post(self, request: Request, message_id: str) -> Response:
        serializer = ReactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.react_message(_me(request), message_id, serializer.validated_data["type"])
        return data_response({"detail": "reacted"})

    @extend_schema(responses={204: None}, tags=["chat"])
    def delete(self, request: Request, message_id: str) -> Response:
        services.unreact_message(_me(request), message_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConversationReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReadSerializer, responses={200: None}, tags=["chat"])
    def post(self, request: Request, conversation_id: str) -> Response:
        serializer = ReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.mark_read(
            _me(request), conversation_id, str(serializer.validated_data["up_to_message_id"])
        )
        return data_response({"detail": "read"})


class ConversationMuteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=MuteSerializer, responses={200: None}, tags=["chat"])
    def post(self, request: Request, conversation_id: str) -> Response:
        from django.utils import timezone

        serializer = MuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        minutes = serializer.validated_data["minutes"]
        until = timezone.now() + timedelta(minutes=minutes) if minutes else None
        services.set_mute(_me(request), conversation_id, until)
        return data_response({"detail": "muted" if minutes else "unmuted"})


class ConversationPinView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PinSerializer, responses={201: None}, tags=["chat"])
    def post(self, request: Request, conversation_id: str) -> Response:
        serializer = PinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.pin_message(
            _me(request), conversation_id, str(serializer.validated_data["message_id"])
        )
        return data_response({"detail": "pinned"}, status=status.HTTP_201_CREATED)

    @extend_schema(request=PinSerializer, responses={204: None}, tags=["chat"])
    def delete(self, request: Request, conversation_id: str) -> Response:
        serializer = PinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.unpin_message(
            _me(request), conversation_id, str(serializer.validated_data["message_id"])
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- inbox state -------------------------------------------------------------


class UnreadView(APIView):
    """The total unread badge (archived and muted conversations left out)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["chat"])
    def get(self, request: Request) -> Response:
        return data_response(services.unread_summary(_me(request)))


class DeliveredView(APIView):
    """Everything that reached this device so far is delivered (ticks)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: None}, tags=["chat"])
    def post(self, request: Request) -> Response:
        return data_response({"conversations": services.mark_delivered(_me(request))})


class ConversationArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ArchiveSerializer, responses={200: ConversationSerializer}, tags=["chat"]
    )
    def post(self, request: Request, conversation_id: str) -> Response:
        serializer = ArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_archived(_me(request), conversation_id, serializer.validated_data["archived"])
        return data_response(_conversation_data(request, conversation_id))


class ConversationClearView(APIView):
    """Clear chat for me: earlier messages disappear for the caller only."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None}, tags=["chat"])
    def post(self, request: Request, conversation_id: str) -> Response:
        services.clear_for_me(_me(request), conversation_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- message lifecycle -------------------------------------------------------


class MessageDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MessageSerializer}, tags=["chat"])
    def get(self, request: Request, message_id: str) -> Response:
        return data_response(MessageSerializer(services.get_message(_me(request), message_id)).data)

    @extend_schema(request=MessageEditSerializer, responses={200: MessageSerializer}, tags=["chat"])
    def patch(self, request: Request, message_id: str) -> Response:
        serializer = MessageEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = services.edit_message(_me(request), message_id, serializer.validated_data["body"])
        return data_response(MessageSerializer(message).data)

    @extend_schema(responses={204: None}, tags=["chat"])
    def delete(self, request: Request, message_id: str) -> Response:
        """``?scope=me`` (default) hides it for the caller; ``?scope=everyone``
        deletes it for all members (sender only, within the delete window)."""
        scope = request.query_params.get("scope", "me")
        if scope == "everyone":
            services.delete_for_everyone(_me(request), message_id)
        elif scope == "me":
            services.hide_for_me(_me(request), message_id)
        else:
            raise TaraAPIError(
                "scope must be 'me' or 'everyone'.", code="validation_error", http_status_code=400
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MessageForwardView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ForwardSerializer, responses={201: MessageSerializer(many=True)}, tags=["chat"]
    )
    def post(self, request: Request, message_id: str) -> Response:
        serializer = ForwardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        copies = services.forward_message(
            _me(request),
            message_id,
            [str(c) for c in serializer.validated_data["conversation_ids"]],
        )
        return data_response(
            MessageSerializer(copies, many=True).data, status=status.HTTP_201_CREATED
        )


class MessageAttachmentView(APIView):
    """A presigned URL for one attachment, minted after the membership check."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["chat"])
    def get(self, request: Request, message_id: str, media_id: str) -> Response:
        return data_response(services.attachment_url(_me(request), message_id, media_id))


# ---- search and shared media -------------------------------------------------


class MessageSearchView(APIView):
    """Search every conversation the caller belongs to (Arabic-normalised)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MessageSerializer(many=True)}, tags=["chat"])
    def get(self, request: Request) -> Response:
        return _paginate(
            request,
            services.search_messages(_me(request), request.query_params.get("q", "")),
            MessageSerializer,
        )


class ConversationSearchView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MessageSerializer(many=True)}, tags=["chat"])
    def get(self, request: Request, conversation_id: str) -> Response:
        return _paginate(
            request,
            services.search_conversation(
                _me(request), conversation_id, request.query_params.get("q", "")
            ),
            MessageSerializer,
        )


class ConversationMediaView(APIView):
    """Shared media panel: ``?kind=image|video|voice|file`` (all when omitted)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SharedMediaSerializer(many=True)}, tags=["chat"])
    def get(self, request: Request, conversation_id: str) -> Response:
        return _paginate(
            request,
            services.shared_media(
                _me(request), conversation_id, request.query_params.get("kind") or None
            ),
            SharedMediaSerializer,
        )
