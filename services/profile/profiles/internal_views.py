"""Internal (service-to-service) API — never exposed at the public edge.

Returns a minimal public profile snapshot for other services (e.g. Posts/Chat
need author display data). Authenticated with a short-lived internal service
token (HS256), NOT a user token.
"""

from __future__ import annotations

from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.auth import verify_internal_token
from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response

from .models import UserProfile


def _require_internal(request: Request) -> None:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    parts = header.split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise TaraAPIError("Internal auth required.", code="unauthenticated", http_status_code=401)
    try:
        verify_internal_token(parts[1], expected_audience="profile-internal")
    except Exception as exc:  # noqa: BLE001
        raise TaraAPIError(
            "Invalid internal token.", code="unauthenticated", http_status_code=401
        ) from exc


MAX_HANDLES = 50


class _HandlesSerializer(serializers.Serializer):
    handles = serializers.ListField(child=serializers.CharField(max_length=60), default=list)


class ProfilesByHandleView(APIView):
    """Resolve @handles to accounts. Unknown handles are simply left out.

    Handles are stored lowercase, so the lookup uses the unique index.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def post(self, request: Request) -> Response:
        _require_internal(request)
        serializer = _HandlesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        handles = [h.lower() for h in serializer.validated_data["handles"]][:MAX_HANDLES]
        rows = UserProfile.objects.filter(handle__in=handles, deleted_at__isnull=True).values_list(
            "handle", "account_id"
        )
        return data_response({handle: str(account) for handle, account in rows})


class ProfileSnapshotView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def get(self, request: Request, account_id: str) -> Response:
        _require_internal(request)
        profile = UserProfile.objects.filter(account_id=account_id, deleted_at__isnull=True).first()
        if profile is None:
            raise TaraAPIError("Profile not found.", code="not_found", http_status_code=404)
        return data_response(
            {
                "account_id": str(profile.account_id),
                "handle": profile.handle,
                "display_name": profile.display_name,
                "avatar_media_id": str(profile.avatar_media_id)
                if profile.avatar_media_id
                else None,
            }
        )
