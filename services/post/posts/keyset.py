"""Opaque keyset cursors on ``(created_at, id)`` descending (Tara Intelligence 4b.9).

``tara_common`` ``CursorPagination`` builds its position from the first order
field only and walks ties with an offset. The reels "seen last" pager and the
full video pages need the whole key (and, for reels, a phase and a snapshot
time), so they use this small codec instead. The token is base64url JSON: the
client treats it as opaque and only ever sends back what it was given.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from django.db.models import Q

from tara_common.exceptions import TaraAPIError


def invalid_cursor() -> TaraAPIError:
    return TaraAPIError("Invalid cursor.", code="validation_error", http_status_code=400)


def encode(fields: dict) -> str:
    raw = json.dumps(fields, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(token: str | None) -> dict | None:
    """The cursor's fields, ``None`` for the first page; garbage is a 400."""
    if not token:
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError):
        raise invalid_cursor() from None
    if not isinstance(data, dict):
        raise invalid_cursor()
    return data


def position(data: dict) -> tuple[datetime, uuid.UUID]:
    """The ``(created_at, id)`` a cursor points after."""
    try:
        at = datetime.fromisoformat(str(data["t"]))
        pk = uuid.UUID(str(data["id"]))
    except (KeyError, TypeError, ValueError):
        raise invalid_cursor() from None
    if at.tzinfo is None:
        raise invalid_cursor()
    return at, pk


def after(at: datetime, pk, *, time_field: str = "created_at", pk_field: str = "pk") -> Q:
    """Rows strictly after ``(at, pk)`` in ``(time_field, pk_field)`` descending order."""
    return Q(**{f"{time_field}__lt": at}) | Q(**{time_field: at, f"{pk_field}__lt": pk})


def mark(at: datetime, pk) -> dict:
    return {"t": at.isoformat(), "id": str(pk)}


def page_size(request, default: int, maximum: int) -> int:
    """``?limit=`` within ``1..maximum`` (the default when absent or garbage)."""
    try:
        value = int(request.query_params.get("limit", default))
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, value))


def envelope(data: list, next_cursor: str | None) -> dict:
    """The Tara page envelope (``prev_cursor`` is not offered by keyset pages)."""
    return {
        "data": data,
        "page": {
            "next_cursor": next_cursor,
            "prev_cursor": None,
            "has_more": next_cursor is not None,
        },
    }
