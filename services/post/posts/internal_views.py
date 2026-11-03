"""Internal post endpoints for other services (media authorising restricted media).

Authenticated with a short-lived internal service token (HS256, aud
'post-internal'). Never exposed at the public edge (nginx and Traefik route
only /api/v1/ prefixes).
"""

from __future__ import annotations

import uuid

from django.db import transaction
from django.utils.decorators import method_decorator
from gatherings.models import Gathering
from gatherings.services import visible_to_viewer as gathering_visible
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.auth import verify_internal_token
from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response

from . import services
from .models import Post


def _require_internal(request: Request) -> None:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    parts = header.split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise TaraAPIError("Internal auth required.", code="unauthenticated", http_status_code=401)
    try:
        verify_internal_token(parts[1], expected_audience="post-internal")
    except Exception as exc:  # noqa: BLE001
        raise TaraAPIError(
            "Invalid internal token.", code="unauthenticated", http_status_code=401
        ) from exc


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # reads; calls graph
class PostVisibilityView(APIView):
    """Can viewer V see post P? The same resolver the public API uses.

    Always 200 with ``visible``; a missing, deleted or removed post is
    ``false``. Graph being down also means ``false`` (fail closed).
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def get(self, request: Request, post_id: uuid.UUID) -> Response:
        _require_internal(request)
        try:
            viewer_id = str(uuid.UUID(request.query_params.get("viewer_id", "")))
        except ValueError as exc:
            raise TaraAPIError(
                "viewer_id must be a UUID.", code="validation_error", http_status_code=400
            ) from exc
        post = Post.objects.filter(id=post_id).first()
        if post is not None:
            visible = services.visible_to_viewer(viewer_id, post)
        else:
            # An event's cover is bound to the event id the same way (no clash:
            # uuid7), so media asks this one endpoint for both.
            gathering = Gathering.objects.filter(id=post_id).first()
            visible = gathering is not None and gathering_visible(viewer_id, gathering)
        return data_response({"post_id": str(post_id), "viewer_id": viewer_id, "visible": visible})
