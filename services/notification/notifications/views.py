"""Notification HTTP API: list, read, preferences, push-token registration."""

from __future__ import annotations

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from . import push, services
from .serializers import (
    NotificationSerializer,
    PreferenceSerializer,
    PreferenceUpdateSerializer,
    PushTokenSerializer,
    PushUnsubscribeSerializer,
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
        serializer = PreferenceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        pref = services.get_or_create_preferences(_me(request))
        if "prefs" in v:
            pref.prefs = v["prefs"]
        if "quiet_hours" in v:
            pref.quiet_hours = v["quiet_hours"]
        pref.save()
        return data_response(PreferenceSerializer(pref).data)


class PushTokenView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PushTokenSerializer, responses={201: None}, tags=["notifications"])
    def post(self, request: Request) -> Response:
        serializer = PushTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        if v["platform"] == "web":
            services.register_web_push(_me(request), v["subscription"])
        else:
            services.register_push_token(_me(request), v["platform"], v["token"])
        return data_response({"detail": "registered"}, status=201)

    @extend_schema(request=PushUnsubscribeSerializer, responses={204: None}, tags=["notifications"])
    def delete(self, request: Request) -> Response:
        serializer = PushUnsubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.unregister_web_push(_me(request), serializer.validated_data["endpoint"])
        return Response(status=204)


class PushConfigView(APIView):
    """What a browser needs to subscribe. ``enabled`` is false without VAPID keys."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["notifications"])
    def get(self, request: Request) -> Response:
        return data_response(
            {"enabled": push.configured(), "public_key": settings.VAPID_PUBLIC_KEY}
        )
