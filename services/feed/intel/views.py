"""Tara Intelligence HTTP endpoints (02 section 7.1)."""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError

from . import clock, preferences, why
from .signals import ingest, validate
from .signals.serializers import SignalBatchSerializer


class SignalsThrottle(UserRateThrottle):
    """60 batches per minute per account (``intel_signals`` in settings)."""

    scope = "intel_signals"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.account_id}


class SignalIngestView(APIView):
    """``POST /api/v1/feed/signals/``: one telemetry batch (served by ``feed-signals``).

    202 with ``{accepted, duplicate, rejected: {reason: n}}``. Invalid events are
    dropped one by one; a batch over 32 KB is refused whole (413).
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [SignalsThrottle]

    @extend_schema(
        request=SignalBatchSerializer, responses={202: OpenApiTypes.OBJECT}, tags=["intel"]
    )
    def post(self, request):
        length = request.META.get("CONTENT_LENGTH") or "0"
        try:
            declared = int(length)
        except ValueError:
            declared = 0
        if declared > validate.MAX_BATCH_BYTES or len(request.body) > validate.MAX_BATCH_BYTES:
            raise TaraAPIError("Batch too large.", code="payload_too_large", http_status_code=413)
        body = SignalBatchSerializer(data=request.data)
        if not body.is_valid():
            raise ValidationError(body.errors)
        account = request.user.account_id
        # WP 4b.15: the test clock (dev, flag on, seed or test account only).
        now = clock.request_now(request, account)
        result = ingest.ingest(account, body.validated_data, now=now)
        return Response({"data": result.as_dict()}, status=status.HTTP_202_ACCEPTED)


class PreferencesSerializer(serializers.Serializer):
    default_mode = serializers.ChoiceField(choices=preferences.MODES)
    version = serializers.IntegerField(required=False, min_value=0)


def _preferences_body(row) -> dict:
    return {"default_mode": row.default_mode or None, "version": row.version}


class PreferencesView(APIView):
    """``GET/PATCH /api/v1/feed/preferences/``: the viewer's own My Algorithm settings.

    WP 4.6 serves the remembered Home mode only. ``default_mode`` is null until the
    viewer picks one (the server default applies). ``version`` guards concurrent
    edits: a PATCH naming an older version gets 409 with the current one.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["intel"])
    def get(self, request):
        return Response({"data": _preferences_body(preferences.get(request.user.account_id))})

    @extend_schema(
        request=PreferencesSerializer, responses={200: OpenApiTypes.OBJECT}, tags=["intel"]
    )
    def patch(self, request):
        body = PreferencesSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            row = preferences.set_default_mode(
                request.user.account_id,
                body.validated_data["default_mode"],
                expected_version=body.validated_data.get("version"),
            )
        except preferences.StaleVersion as exc:
            raise TaraAPIError(
                "Preferences changed elsewhere.", code="conflict", http_status_code=409
            ) from exc
        return Response({"data": _preferences_body(row)})


class WhyView(APIView):
    """``GET /api/v1/feed/why/{item_type}/{item_id}/`` (02 section 20, WP 4.8).

    The item's serve token goes in ``?st=`` (or the ``X-Serve-Token`` header). The
    reply is 404, with the same body, for a missing item, an item the viewer may
    not see, and an item never served to this viewer: no existence oracle.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT}, tags=["intel"])
    def get(self, request, item_type: str, item_id: str):
        token = request.query_params.get("st") or request.headers.get("X-Serve-Token")
        body = why.explain(request.user.claims, item_type, item_id, token)
        if body is None:
            raise NotFound()
        return Response({"data": body})
