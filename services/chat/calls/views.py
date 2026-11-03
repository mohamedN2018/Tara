"""Calls API (roadmap 3.7, 3.8) and the LiveKit webhook receiver."""

from __future__ import annotations

import logging

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from tara_common.responses import data_response
from tara_common.throttling import ReadThrottle, WriteThrottle

from . import livekit, services
from .serializers import CallSerializer, StartCallSerializer

logger = logging.getLogger("tara.chat.calls.webhook")


def _me(request: Request) -> str:
    return request.user.account_id


class CallStartThrottle(SimpleRateThrottle):
    """Starting a call rings other people's devices: a tighter per-account limit."""

    scope = "call_start"

    def get_rate(self) -> str:
        return settings.CALL_START_RATE

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.account_id}


def _grant_data(grant: dict) -> dict:
    return {
        "call_id": grant["call_id"],
        "room": grant["room"],
        "token": grant["token"],
        "url": grant["url"],
        "call": CallSerializer(services.with_participants(grant["call"])).data,
    }


def _call_data(call) -> dict:
    return CallSerializer(services.with_participants(call)).data


class CallConfigView(APIView):
    """Whether calls are on. 200 either way; the SPA hides call buttons when off."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["calls"])
    def get(self, request: Request) -> Response:
        return data_response(services.config())


class ConversationCallsView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadThrottle, WriteThrottle, CallStartThrottle]

    @extend_schema(request=StartCallSerializer, responses={201: None, 200: None}, tags=["calls"])
    def post(self, request: Request, conversation_id: str) -> Response:
        """Start a call, or join the conversation's live call (200)."""
        services.require_enabled()
        serializer = StartCallSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grant, created = services.start_call(
            _me(request), conversation_id, serializer.validated_data["kind"]
        )
        return data_response(
            _grant_data(grant), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


class ActiveCallView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CallSerializer}, tags=["calls"])
    def get(self, request: Request, conversation_id: str) -> Response:
        call = services.active_call(_me(request), conversation_id)
        return data_response(CallSerializer(call).data if call else None)


class CallJoinView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: None}, tags=["calls"])
    def post(self, request: Request, call_id: str) -> Response:
        return data_response(_grant_data(services.join_call(_me(request), call_id)))


class CallDeclineView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: CallSerializer}, tags=["calls"])
    def post(self, request: Request, call_id: str) -> Response:
        return data_response(_call_data(services.decline_call(_me(request), call_id)))


class CallEndView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: CallSerializer}, tags=["calls"])
    def post(self, request: Request, call_id: str) -> Response:
        return data_response(_call_data(services.end_call(_me(request), call_id)))


def _error(status_code: int, code: str, message: str) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status_code)


@csrf_exempt
@require_POST
def livekit_webhook(request: HttpRequest) -> JsonResponse:
    """LiveKit's signed webhook (``application/webhook+json``, which DRF rejects).

    The signature is checked against the **raw body**: the Authorization JWT is
    signed with the API secret and carries the body's SHA-256. Not routed by the
    edge (nginx and Traefik never forward ``/internal/``); the signature is
    checked anyway, so it is the gate even if that ever changed.
    """
    if not livekit.enabled():
        return _error(503, "calls_unavailable", "Calls are not available.")
    try:
        body = request.body.decode("utf-8")
    except UnicodeDecodeError:
        return _error(400, "validation_error", "The body is not UTF-8.")
    try:
        event = livekit.receive_webhook(body, request.headers.get("Authorization", ""))
    except Exception:  # noqa: BLE001 - any verification failure is a 401
        logger.warning("rejected a LiveKit webhook with a bad signature")
        return _error(401, "authentication_failed", "Invalid webhook signature.")
    outcome = services.apply_webhook(event)
    return JsonResponse({"data": {"outcome": outcome}})
