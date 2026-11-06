"""Opaque cursor pagination used across timeline-like endpoints.

Wraps DRF's CursorPagination but emits the Tara envelope:

    {"data": [...], "page": {"next_cursor": "...", "prev_cursor": "...", "has_more": bool}}

Cursors are opaque base64 (sort_key + tiebreaker), stable under inserts — never
raw offsets. See docs/architecture/phase-0/03-api-contracts.md §4.
"""

from __future__ import annotations

import base64
import binascii
import json

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination as DRFCursorPagination
from rest_framework.response import Response


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


class KeysetCursorPagination(CursorPagination):
    """A true keyset over ``(key_field desc, id_field desc)`` (Tara Intelligence 08
    section 7.3, WP 4c.8-B3).

    ``CursorPagination`` encodes only the first ordering field plus an offset for
    ties, so a tied row inserted or deleted between two pages can skip or repeat a
    row. This class encodes the last row's ``(key, id)`` and reads strictly below
    it: ``key < t OR (key = t AND id < i)``. Inserts above the cursor and deletes
    anywhere cannot shift it.

    - Same envelope as ``CursorPagination``; ``prev_cursor`` is always null.
    - The token is opaque: base64url JSON ``{"k": "t", "t": <key>, "i": <id>}``.
    - One query per page (``size + 1`` rows, the extra one sets ``has_more``).
    - A cursor the server cannot read answers 404 (``invalid_cursor_message``).
    - A cursor issued by ``CursorPagination`` before the switch (in flight in open
      tabs) is still read, for one release: it continues the way it was issued
      (rows below its position, its offset skipping the ties it already served),
      and the next cursor of that page is a keyset one.

    The queryset's own ordering is replaced by the keyset ordering; the field names
    are class attributes so another service can reuse the class.
    """

    key_field = "created_at"
    id_field = "id"
    # Accept ``CursorPagination`` tokens (remove one release after the switch).
    accept_legacy_cursor = True

    def get_ordering(self, request, queryset, view) -> tuple[str, ...]:
        return (f"-{self.key_field}", f"-{self.id_field}")

    # ---- token -------------------------------------------------------------------

    def encode_keyset(self, instance) -> str:
        key = getattr(instance, self.key_field)
        ident = getattr(instance, self.id_field)
        raw = json.dumps(
            {"k": "t", "t": key.isoformat() if hasattr(key, "isoformat") else key, "i": str(ident)},
            separators=(",", ":"),
        )
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @staticmethod
    def _read_keyset(token: str) -> dict | None:
        """The keyset payload of ``token``, or None when it is not a keyset token."""
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            data = json.loads(raw.decode())
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return None
        if isinstance(data, dict) and data.get("k") == "t" and {"t", "i"} <= set(data):
            return data
        return None

    def _position(self, queryset, data: dict):
        meta = queryset.model._meta
        try:
            key = meta.get_field(self.key_field).to_python(data["t"])
            ident = meta.get_field(self.id_field).to_python(data["i"])
        except (DjangoValidationError, TypeError, ValueError) as exc:
            raise NotFound(self.invalid_cursor_message) from exc
        if key is None or ident is None:
            raise NotFound(self.invalid_cursor_message)
        return key, ident

    # ---- paging ------------------------------------------------------------------

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        token = request.query_params.get(self.cursor_query_param)
        keyset = self._read_keyset(token) if token else None
        self.legacy_cursor = bool(token) and keyset is None
        if self.legacy_cursor:
            if not self.accept_legacy_cursor:
                raise NotFound(self.invalid_cursor_message)
            # ``CursorPagination`` reads (and rejects with 404) its own token.
            page = super().paginate_queryset(queryset, request, view)
        else:
            self.page_size = self.get_page_size(request)
            queryset = queryset.order_by(*self.get_ordering(request, queryset, view))
            if keyset is not None:
                key, ident = self._position(queryset, keyset)
                # ``key <= t`` is redundant with the OR but lets the index range-scan
                # from the cursor instead of filtering every row above it.
                queryset = queryset.filter(
                    Q(**{f"{self.key_field}__lt": key})
                    | Q(**{self.key_field: key, f"{self.id_field}__lt": ident}),
                    **{f"{self.key_field}__lte": key},
                )
            rows = list(queryset[: self.page_size + 1])
            page = rows[: self.page_size]
            self.has_next = len(rows) > len(page)
            self.has_previous = False
            self.page = page
        self.next_token = self.encode_keyset(page[-1]) if self.has_next and page else None
        return page

    def get_paginated_response(self, data) -> Response:
        return Response(
            {
                "data": data,
                "page": {
                    "next_cursor": self.next_token,
                    "prev_cursor": None,
                    "has_more": self.next_token is not None,
                },
            }
        )
