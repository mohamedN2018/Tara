"""Uniform success envelope helpers.

All Tara services return the same response shape so web / iOS / Android clients
parse one contract. See docs/architecture/phase-0/03-api-contracts.md.
"""

from __future__ import annotations

from typing import Any

from rest_framework.response import Response


def data_response(data: Any, status: int = 200, headers: dict | None = None) -> Response:
    """Wrap a single resource (or already-shaped payload) as ``{"data": ...}``."""
    return Response({"data": data}, status=status, headers=headers)


def collection_response(
    items: list[Any],
    *,
    next_cursor: str | None = None,
    prev_cursor: str | None = None,
    status: int = 200,
) -> Response:
    """Wrap a list with cursor pagination metadata.

    Prefer :class:`tara_common.pagination.CursorPagination` for queryset-backed
    endpoints; this helper is for hand-built collections.
    """
    return Response(
        {
            "data": items,
            "page": {
                "next_cursor": next_cursor,
                "prev_cursor": prev_cursor,
                "has_more": next_cursor is not None,
            },
        },
        status=status,
    )
