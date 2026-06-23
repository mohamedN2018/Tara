"""Internal: Feed asks for a sponsored creative to blend into a viewer's feed."""

from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.auth import verify_internal_token
from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response

from . import services


def _require_internal(request: Request) -> None:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    parts = header.split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise TaraAPIError("Internal auth required.", code="unauthenticated", http_status_code=401)
    try:
        verify_internal_token(parts[1], expected_audience="ads-internal")
    except Exception as exc:  # noqa: BLE001
        raise TaraAPIError(
            "Invalid internal token.", code="unauthenticated", http_status_code=401
        ) from exc


class FeedSlotView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request) -> Response:
        _require_internal(request)
        viewer = request.query_params.get("viewer", "")
        placement = request.query_params.get("placement", "feed")
        creative = services.pick_for_viewer(viewer, placement) if viewer else None
        return data_response({"sponsored": creative})
