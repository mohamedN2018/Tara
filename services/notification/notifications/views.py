"""Notification HTTP API: list, read, preferences, push-token registration."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from . import services
from .serializers import (
    NotificationSerializer,
    PreferenceSerializer,
    PreferenceUpdateSerializer,
    PushTokenSerializer,
    ReadSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


class NotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: NotificationSerializer(many=True)}, tags=["notifications"])
    def get(self, request: Request) -> Response:
        unread_only = request.query_params.get("unread") in ("1", "true")
        qs = services.list_for(_me(request), unread_only=unread_only)
        paginator = CursorPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(NotificationSerializer(page, many=True).data)


class UnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["notifications"])
    def get(self, request: Request) -> Response:
        return data_response({"unread": services.unread_count(_me(request))})


class ReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReadSerializer, responses={200: None}, tags=["notifications"])
    def post(self, request: Request) -> Response:
        serializer = ReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        count = services.mark_read(_me(request), ids=[str(i) for i in v["ids"]], mark_all=v["all"])
        return data_response({"marked_read": count})


class PreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PreferenceSerializer}, tags=["notifications"])
    def get(self, request: Request) -> Response:
        pref = services.get_or_create_preferences(_me(request))
        return data_response(PreferenceSerializer(pref).data)

    @extend_schema(
        request=PreferenceSerializer, responses={200: PreferenceSerializer}, tags=["notifications"]
    )
    def patch(self, request: Request) -> Response:
        pref = services.get_or_create_preferences(_me(request))
        if "prefs" in request.data:
            serializer = PreferenceUpdateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            pref.prefs = serializer.validated_data["prefs"]
        if "quiet_hours" in request.data:
            pref.quiet_hours = request.data["quiet_hours"]
        pref.save()
        return data_response(PreferenceSerializer(pref).data)


class PushTokenView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PushTokenSerializer, responses={201: None}, tags=["notifications"])
    def post(self, request: Request) -> Response:
        serializer = PushTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.register_push_token(
            _me(request), serializer.validated_data["platform"], serializer.validated_data["token"]
        )
        return data_response({"detail": "registered"}, status=201)
