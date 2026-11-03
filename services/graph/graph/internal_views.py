"""Internal relationship lookup — consumed by the Profile service for privacy.

Authenticated with a short-lived internal service token (HS256, aud
'graph-internal'). Never exposed at the public edge.
"""

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
        a = request.query_params.get("a")
        b = request.query_params.get("b")
        if not a or not b:
            raise TaraAPIError(
                "Both 'a' and 'b' are required.", code="validation_error", http_status_code=400
            )
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
