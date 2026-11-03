"""Internal platform-statistics endpoint (roadmap 8.11).

Each owning service counts its own rows; admin's beat task polls
``GET /internal/v1/stats/`` on each of them and keeps the latest values. A count
straight from the owner's table is exact, needs no backfill and cannot drift,
which counters kept from events could (missed, replayed or reordered events).

Authenticated like the other read-only internal endpoints: a short-lived HS256
token for audience ``<SERVICE_NAME>-internal``. Never routed by the edge. The
response holds only aggregate integers, no ids or content.

Mount it in a service's URLconf:

    path("internal/v1/stats/", InternalStatsView.as_view(counters={"posts": count_posts}))
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from django.conf import settings
from django.db import transaction
from django.utils.decorators import method_decorator
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import verify_internal_token
from .exceptions import TaraAPIError
from .responses import data_response

logger = logging.getLogger("tara.common.stats")


def require_internal_token(request: Request, audience: str) -> None:
    """Raise 401 unless the request carries a valid internal token for ``audience``."""
    parts = request.META.get("HTTP_AUTHORIZATION", "").split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise TaraAPIError("Internal auth required.", code="unauthenticated", http_status_code=401)
    try:
        verify_internal_token(parts[1], expected_audience=audience)
    except Exception as exc:  # noqa: BLE001 - any doubt is a refusal
        raise TaraAPIError(
            "Invalid internal token.", code="unauthenticated", http_status_code=401
        ) from exc


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # read-only counts
class InternalStatsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)
    counters: dict[str, Callable[[], int]] = {}

    def get(self, request: Request) -> Response:
        require_internal_token(request, f"{settings.SERVICE_NAME}-internal")
        values: dict[str, int | None] = {}
        for metric, count in self.counters.items():
            try:
                values[metric] = int(count())
            except Exception:  # noqa: BLE001 - one broken counter must not hide the rest
                logger.exception("stats counter failed", extra={"metric": metric})
                values[metric] = None
        return data_response({"service": settings.SERVICE_NAME, "stats": values})
