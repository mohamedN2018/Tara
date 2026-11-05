"""Tara Intelligence HTTP endpoints (02 section 7.1)."""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError

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
        result = ingest.ingest(request.user.account_id, body.validated_data)
        return Response({"data": result.as_dict()}, status=status.HTTP_202_ACCEPTED)
