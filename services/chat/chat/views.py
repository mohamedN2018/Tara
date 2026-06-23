"""Chat HTTP API: conversations, messages, voice notes, reactions, reads, mute, pin."""

from __future__ import annotations

from datetime import timedelta

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from . import services
from .models import Message
from .serializers import (
    ConversationSerializer,
    DMCreateSerializer,
    GroupCreateSerializer,
    MessageCreateSerializer,
    MessageSerializer,
    MuteSerializer,
    PinSerializer,
    ReactionSerializer,
    ReadSerializer,
    VoiceMessageSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


def _paginate(request, queryset, serializer_cls):
    paginator = CursorPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(serializer_cls(page, many=True).data)


class ConversationsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ConversationSerializer(many=True)}, tags=["chat"])
    def get(self, request: Request) -> Response:
        return _paginate(request, services.list_conversations(_me(request)), ConversationSerializer)

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
            ConversationSerializer(conversation).data, status=status.HTTP_201_CREATED
        )


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
