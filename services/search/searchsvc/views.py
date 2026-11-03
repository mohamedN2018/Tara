"""Search HTTP API: query + autocomplete."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.responses import data_response

from . import backend
from .models import SearchDocument


class SearchView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["search"])
    def get(self, request: Request) -> Response:
        q = request.query_params.get("q", "").strip()
        doc_type = request.query_params.get("type")
        if doc_type and doc_type not in SearchDocument.DOC_TYPES:
            doc_type = None
        raw_limit = request.query_params.get("limit", "20")
        limit = min(int(raw_limit), 50) if raw_limit.isdecimal() else 20
        results, degraded = backend.query(
            q, viewer_id=request.user.account_id, doc_type=doc_type, limit=limit
        )
        return data_response(
            {"results": results, "degraded": degraded, "query": q, "type": doc_type}
        )


class AutocompleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["search"])
    def get(self, request: Request) -> Response:
        prefix = request.query_params.get("q", "").strip()
        if not prefix:
            return data_response({"results": []})
        return data_response(
            {"results": backend.autocomplete(prefix, viewer_id=request.user.account_id)}
        )
