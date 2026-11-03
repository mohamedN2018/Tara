"""Internal media endpoints for other services (Post attaching media)."""

from __future__ import annotations

from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.auth import verify_internal_token
from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response

from . import services
from .models import MediaAsset

MAX_BATCH = 100
MAX_BIND = 20


def _require_internal(request: Request) -> None:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    parts = header.split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise TaraAPIError("Internal auth required.", code="unauthenticated", http_status_code=401)
    try:
        verify_internal_token(parts[1], expected_audience="media-internal")
    except Exception as exc:  # noqa: BLE001
        raise TaraAPIError(
            "Invalid internal token.", code="unauthenticated", http_status_code=401
        ) from exc


class InternalMediaView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def get(self, request: Request, media_id: str) -> Response:
        _require_internal(request)
        asset = MediaAsset.objects.filter(id=media_id, deleted_at__isnull=True).first()
        if asset is None:
            raise TaraAPIError("Media not found.", code="not_found", http_status_code=404)
        payload = services.asset_payload(asset)
        payload["owner_id"] = str(asset.owner_id)
        return data_response(payload)


class _BatchSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), max_length=MAX_BATCH)


class InternalMediaBatchView(APIView):
    """Owner, kind, status and attachment of many media; missing ids are left out."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def post(self, request: Request) -> Response:
        _require_internal(request)
        serializer = _BatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = [str(i) for i in serializer.validated_data["ids"]]
        return data_response(services.internal_lookup(ids))


class _BindSerializer(serializers.Serializer):
    owner_id = serializers.UUIDField()
    post_id = serializers.UUIDField()
    media_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=MAX_BIND
    )
    restricted = serializers.BooleanField()


class InternalMediaBindView(APIView):
    """Attach media to a post; ``restricted`` media then follow the post's audience."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def post(self, request: Request) -> Response:
        _require_internal(request)
        serializer = _BindSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        result = services.bind_to_post(
            str(v["owner_id"]),
            str(v["post_id"]),
            [str(m) for m in v["media_ids"]],
            restricted=v["restricted"],
        )
        return data_response(result)
