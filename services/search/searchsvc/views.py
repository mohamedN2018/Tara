"""Search HTTP API (v2, roadmap 1.15).

- ``GET /search/``: unified results by tab, contextual filters, keyset pages.
- ``GET /search/suggest/`` (and the older ``/search/autocomplete/``): fast
  autocomplete over people, pages, groups and hashtags, one SQL query.
- ``/search/recent/``: the caller's own search history (list, add, clear;
  ``/search/recent/<id>/`` deletes one entry).
- ``GET /search/trending/``: hashtags trending in public posts.

All reads are non-atomic (no write, so no transaction or savepoint per request).
"""

from __future__ import annotations

from django.db import transaction
from django.utils.decorators import method_decorator
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response

from . import backend, engine, history, results

MAX_LIMIT = 50
DEFAULT_LIMIT = 20
SUGGEST_LIMIT = 8


def _limit(raw: str | None, default: int, cap: int) -> int:
    return min(max(int(raw), 1), cap) if raw and raw.isdecimal() else default


def _bad(message: str, field: str) -> TaraAPIError:
    return TaraAPIError(
        message,
        code="validation_error",
        http_status_code=400,
        details=[{"field": field, "code": "invalid", "message": message}],
    )


_SEARCH_PARAMS = [
    OpenApiParameter("q", str),
    OpenApiParameter("type", str, enum=engine.TABS),
    OpenApiParameter("sort", str, enum=list(engine.SORTS)),
    OpenApiParameter("date", str, enum=list(engine.DATE_PRESETS)),
    OpenApiParameter("from", str, description="YYYY-MM-DD"),
    OpenApiParameter("to", str, description="YYYY-MM-DD"),
    OpenApiParameter("category", str),
    OpenApiParameter("location", str),
    OpenApiParameter("cursor", str),
    OpenApiParameter("limit", int),
]


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class SearchView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=_SEARCH_PARAMS, responses={200: None}, tags=["search"])
    def get(self, request: Request) -> Response:
        params = request.query_params
        q = params.get("q", "").strip()[: engine.MAX_QUERY]
        tab = engine.resolve_tab(params.get("type"))
        limit = _limit(params.get("limit"), DEFAULT_LIMIT, MAX_LIMIT)
        viewer = request.user.account_id
        degraded = False
        cursor = params.get("cursor") or None
        if backend.opensearch_enabled() and tab == "all" and not cursor:
            # The optional accelerator only serves the first unfiltered page.
            hits, degraded = backend.query(q, viewer_id=viewer, limit=limit)
            docs, next_cursor = None, None
        else:
            try:
                docs, next_cursor = engine.search(
                    q,
                    viewer_id=viewer,
                    doc_types=engine.TAB_TYPES.get(tab),
                    filters=engine.parse_filters(params, tab),
                    cursor=cursor,
                    limit=limit,
                )
            except engine.BadCursor as exc:
                raise _bad("Invalid cursor.", "cursor") from exc
            hits = results.serialize(docs, viewer)
        return Response(
            {
                "data": {
                    "results": hits,
                    "degraded": degraded,
                    "query": q,
                    "type": tab,
                    "types": engine.TABS,
                },
                "page": {"next_cursor": next_cursor, "has_more": next_cursor is not None},
            }
        )


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class SuggestView(APIView):
    """Autocomplete: at most ``SUGGEST_LIMIT`` hits, no graph call, one query."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("q", str), OpenApiParameter("limit", int)],
        responses={200: None},
        tags=["search"],
    )
    def get(self, request: Request) -> Response:
        q = request.query_params.get("q", "").strip()[: engine.MAX_QUERY]
        limit = _limit(request.query_params.get("limit"), SUGGEST_LIMIT, SUGGEST_LIMIT)
        viewer = request.user.account_id
        docs = engine.suggest(q, viewer_id=viewer, limit=limit) if q else []
        return data_response({"results": results.serialize(docs, viewer, decorate=False)})


class AutocompleteView(SuggestView):
    """The v1 path, kept for older clients: same answer as ``/search/suggest/``."""


class RecentSearchSerializer(serializers.Serializer):
    query = serializers.CharField(required=False, allow_blank=True, max_length=200)
    doc_type = serializers.CharField(required=False, allow_blank=True, max_length=16)
    doc_id = serializers.CharField(required=False, allow_blank=True, max_length=100)

    def validate(self, attrs):
        if bool(attrs.get("doc_type")) != bool(attrs.get("doc_id")):
            raise serializers.ValidationError("doc_type and doc_id go together.")
        if not attrs.get("doc_type") and not (attrs.get("query") or "").strip():
            raise serializers.ValidationError("Give a query or a doc_type and doc_id.")
        return attrs


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # writes open their own
class RecentSearchesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["search"])
    def get(self, request: Request) -> Response:
        return data_response(history.recent(request.user.account_id))

    @extend_schema(request=RecentSearchSerializer, responses={201: None}, tags=["search"])
    def post(self, request: Request) -> Response:
        ser = RecentSearchSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        v = ser.validated_data
        try:
            row = history.record(
                request.user.account_id,
                query=v.get("query") or "",
                doc_type=v.get("doc_type") or "",
                doc_id=v.get("doc_id") or "",
            )
        except history.NotSearchable as exc:
            raise TaraAPIError("Not found.", code="not_found", http_status_code=404) from exc
        return data_response(history.serialize_row(row), status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None}, tags=["search"])
    def delete(self, request: Request) -> Response:
        history.clear(request.user.account_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RecentSearchDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None, 404: None}, tags=["search"])
    def delete(self, request: Request, entry_id) -> Response:
        if not history.forget(request.user.account_id, entry_id):
            # Someone else's entry looks exactly like a missing one.
            raise TaraAPIError("Not found.", code="not_found", http_status_code=404)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class TrendingView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("window", str, enum=list(history.TRENDING_WINDOWS))],
        responses={200: None},
        tags=["search"],
    )
    def get(self, request: Request) -> Response:
        return data_response(history.trending(request.query_params.get("window") or "week"))
