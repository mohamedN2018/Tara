"""Internal media lookup for other services (e.g. Post attaching media)."""

from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.auth import verify_internal_token
from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response

from . import services
from .models import MediaAsset


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

    def get(self, request: Request, media_id: str) -> Response:
        _require_internal(request)
        asset = MediaAsset.objects.filter(id=media_id, deleted_at__isnull=True).first()
        if asset is None:
            raise TaraAPIError("Media not found.", code="not_found", http_status_code=404)
        payload = services.asset_payload(asset)
        payload["owner_id"] = str(asset.owner_id)
        return data_response(payload)
