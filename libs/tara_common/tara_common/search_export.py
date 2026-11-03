"""Paged export of searchable rows for search's backfill (roadmap 1.15).

Each owner mounts one view per kind under ``/internal/v1/search/export/<kind>/``
(never routed by the edge). It returns what may be searched today, in the same
payload shape as the owner's events, so search indexes a backfilled row exactly
as it indexes an event:

    {"data": {"as_of": "<owner clock before the read>",
              "items": [{"id": "...", "payload": {...}}],
              "next": "<last primary key>" | null}}

Authenticated like the other read-only internal endpoints: a short-lived HS256
token for audience ``<SERVICE_NAME>-internal``.

    path("search/export/people/", SearchExportView.as_view(
        source=lambda: UserProfile.objects.filter(...),
        to_item=lambda p: (p.account_id, payload(p)),
    ))
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import TaraAPIError
from .responses import data_response
from .stats import require_internal_token

MAX_LIMIT = 500


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # read-only
class SearchExportView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)
    # Set through ``as_view(source=..., to_item=...)``.
    source: Callable[[], Any] | None = None
    to_item: Callable[[Any], tuple[Any, dict]] | None = None

    def get(self, request: Request) -> Response:
        require_internal_token(request, f"{settings.SERVICE_NAME}-internal")
        raw = request.query_params.get("limit", "200")
        limit = min(max(int(raw), 1), MAX_LIMIT) if raw.isdecimal() else 200
        after = request.query_params.get("after") or None
        as_of = timezone.now()  # before the read: a later change has a later event
        qs = self.source()
        if after:
            try:
                qs = qs.filter(pk__gt=uuid.UUID(after))
            except ValueError as exc:
                raise TaraAPIError(
                    "Invalid cursor.", code="validation_error", http_status_code=400
                ) from exc
        rows = list(qs.order_by("pk")[: limit + 1])
        more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for row in rows:
            item_id, payload = self.to_item(row)
            items.append({"id": str(item_id), "payload": payload})
        return data_response(
            {
                "as_of": as_of.isoformat(),
                "items": items,
                "next": str(rows[-1].pk) if more and rows else None,
            }
        )
