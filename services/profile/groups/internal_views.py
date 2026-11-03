"""Internal group endpoints (never routed by the edge).

``access`` is post's synchronous check before a group post or comment is
written, and its fallback when its read model has no row. Authenticated with a
short-lived internal token (aud ``profile-internal``).
"""

from __future__ import annotations

import uuid

from profiles.internal_views import _require_internal
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response

from . import services


class GroupAccessView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def get(self, request: Request, group_id: uuid.UUID) -> Response:
        _require_internal(request)
        try:
            account_id = str(uuid.UUID(request.query_params.get("account_id", "")))
        except ValueError as exc:
            raise TaraAPIError(
                "account_id must be a UUID.", code="validation_error", http_status_code=400
            ) from exc
        found = services.access(str(group_id), account_id)
        if found is None:
            raise TaraAPIError("Group not found.", code="not_found", http_status_code=404)
        return data_response(found)
