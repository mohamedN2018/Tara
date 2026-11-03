"""Internal relationship lookup — consumed by the Profile service for privacy.

Authenticated with a short-lived internal service token (HS256, aud
'graph-internal'). Never exposed at the public edge.
"""

from __future__ import annotations

import uuid

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
        verify_internal_token(parts[1], expected_audience="graph-internal")
    except Exception as exc:  # noqa: BLE001
        raise TaraAPIError(
            "Invalid internal token.", code="unauthenticated", http_status_code=401
        ) from exc


class RelationshipView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request) -> Response:
        _require_internal(request)
        try:
            a, b = (str(uuid.UUID(request.query_params.get(k) or "")) for k in ("a", "b"))
        except ValueError as exc:
            raise TaraAPIError(
                "Both 'a' and 'b' must be UUIDs.", code="validation_error", http_status_code=400
            ) from exc
        return data_response(services.relationship(a, b))


class FanoutAudienceView(APIView):
    """Who should receive an author's post, for Feed fan-out-on-write.

    Returns followers + friends of the author (deduped), never an account with a
    block toward the author in either direction (even if a stale edge survived a
    race with block()). The Feed service decides which subset applies per post
    audience.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request, account_id: str) -> Response:
        _require_internal(request)
        followers = set(services.follower_ids(account_id))
        friends = set(services.list_friend_ids(account_id))
        return data_response(
            {
                "account_id": str(account_id),
                "followers": sorted(followers),
                "friends": sorted(friends),
                "recipients": sorted(followers | friends),
            }
        )


class RelationshipBatchView(APIView):
    """The viewer's relationship with up to 50 accounts and 50 pages (search v2,
    roadmap 1.15): friend state with the pending request id, follow state, and
    the mutual friend count where the target's lists are visible to the viewer;
    for pages, follow state and follower count. Accounts in a block with the
    viewer, either way, are absent from the answer."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def post(self, request: Request) -> Response:
        _require_internal(request)
        body = request.data if isinstance(request.data, dict) else {}
        try:
            viewer = str(uuid.UUID(str(body.get("viewer_id") or "")))
        except ValueError as exc:
            raise TaraAPIError(
                "viewer_id must be a UUID.", code="validation_error", http_status_code=400
            ) from exc
        users, pages = body.get("users") or [], body.get("pages") or []
        if not isinstance(users, list) or not isinstance(pages, list):
            raise TaraAPIError(
                "users and pages must be lists.", code="validation_error", http_status_code=400
            )
        return data_response({"results": services.relationships_for(viewer, users, pages)})
