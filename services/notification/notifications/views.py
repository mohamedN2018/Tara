"""Notification HTTP API: list, read, preferences, push-token registration."""

from __future__ import annotations

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from . import push, registry, services
from .serializers import (
    NotificationSerializer,
    PreferenceSerializer,
    PreferenceUpdateSerializer,
    PushTokenSerializer,
    PushUnsubscribeSerializer,
    ReadSerializer,
    ResolveSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


class NotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: NotificationSerializer(many=True)}, tags=["notifications"])
    def get(self, request: Request) -> Response:
        unread_only = request.query_params.get("unread") in ("1", "true")
        category = request.query_params.get("category", "")
        if category not in ("", *registry.CATEGORIES):
            raise ValidationError({"category": "Unknown category."})
        # `kind`: one notification kind (the Support inbox's "Notices from Tara").
        kind = request.query_params.get("kind", "")
        if kind and kind not in registry.KINDS:
            raise ValidationError({"kind": "Unknown kind."})
        qs = services.list_for(_me(request), unread_only=unread_only, category=category, kind=kind)
        paginator = CursorPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(NotificationSerializer(page, many=True).data)


def _not_found() -> TaraAPIError:
    return TaraAPIError("Notification not found.", code="not_found", http_status_code=404)


class NotificationDetailView(APIView):
    """One notification (the live list fetches rows announced by id), or dismiss it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: NotificationSerializer}, tags=["notifications"])
    def get(self, request: Request, pk) -> Response:
        notification = services.get_for(_me(request), str(pk))
        if notification is None:
            raise _not_found()
        return data_response(NotificationSerializer(notification).data)

    @extend_schema(responses={204: None}, tags=["notifications"])
    def delete(self, request: Request, pk) -> Response:
        services.delete(_me(request), str(pk))  # idempotent: gone is gone
        return Response(status=204)


class ResolveView(APIView):
    """Record the outcome of an inline action (accepted, declined, followed back)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ResolveSerializer, responses={200: NotificationSerializer}, tags=["notifications"]
    )
    def post(self, request: Request, pk) -> Response:
        serializer = ResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            notification = services.resolve(
                _me(request), str(pk), serializer.validated_data["resolution"]
            )
        except ValueError as exc:
            raise ValidationError({"resolution": "Not allowed for this notification."}) from exc
        if notification is None:
            raise _not_found()
        return data_response(NotificationSerializer(notification).data)


class KindsView(APIView):
    """The kind registry: categories and default channels, for the Settings screen."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["notifications"])
    def get(self, request: Request) -> Response:
        return data_response(
            {"categories": list(registry.CATEGORIES), "kinds": registry.describe()}
        )


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
        pref = services.update_preferences(_me(request), serializer.validated_data)
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
