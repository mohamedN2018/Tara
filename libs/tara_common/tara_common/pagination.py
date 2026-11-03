"""Opaque cursor pagination used across timeline-like endpoints.

Wraps DRF's CursorPagination but emits the Tara envelope:

    {"data": [...], "page": {"next_cursor": "...", "prev_cursor": "...", "has_more": bool}}

Cursors are opaque base64 (sort_key + tiebreaker), stable under inserts — never
raw offsets. See docs/architecture/phase-0/03-api-contracts.md §4.
"""

from __future__ import annotations

from rest_framework.pagination import CursorPagination as DRFCursorPagination
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param


class CursorPagination(DRFCursorPagination):
    page_size = 20
    max_page_size = 100
    page_size_query_param = "limit"
    ordering = "-created_at"
    cursor_query_param = "cursor"

    def get_ordering(self, request, queryset, view) -> tuple[str, ...]:
        """Use the queryset's explicit ``order_by``; ``ordering`` is only the default.

        The cursor position comes from the first field, so that field must be
        non-null. Ties in it are walked with an offset capped at ``offset_cutoff``.
        """
        explicit = queryset.query.order_by
        if explicit:
            return tuple(str(field) for field in explicit)
        return super().get_ordering(request, queryset, view)

    def _cursor_token(self, url: str | None) -> str | None:
        """Extract just the opaque cursor token from a DRF-built URL."""
        if not url:
            return None
        # DRF embeds the cursor as a query param; pull it back out.
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(url).query)
        values = qs.get(self.cursor_query_param)
        return values[0] if values else None

    def get_paginated_response(self, data) -> Response:
        return Response(
            {
                "data": data,
                "page": {
                    "next_cursor": self._cursor_token(self.get_next_link()),
                    "prev_cursor": self._cursor_token(self.get_previous_link()),
                    "has_more": self.has_next,
                },
            }
        )

    def get_paginated_response_schema(self, schema: dict) -> dict:
        return {
            "type": "object",
            "properties": {
                "data": schema,
                "page": {
                    "type": "object",
                    "properties": {
                        "next_cursor": {"type": "string", "nullable": True},
                        "prev_cursor": {"type": "string", "nullable": True},
                        "has_more": {"type": "boolean"},
                    },
                },
            },
        }


# Silence unused-import linters for the helpers re-exported for convenience.
__all__ = ["CursorPagination", "remove_query_param", "replace_query_param"]
