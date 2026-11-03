"""Keyset pagination on (sort key, id) for marketplace lists.

DRF's cursor walks ties in the sort key with an OFFSET capped at 1000, so a
price sort with more than 1000 "no price" listings repeats or drops rows. Here
the cursor carries the last row's (key, id) and the next page is the rows after
it, so equal keys and a null tail page correctly in both directions.

Rows whose key is null always come last (QTech's ``price_unset`` rule): a listing
with no price cannot be ranked against priced ones in either direction.

Same response envelope as ``tara_common.pagination.CursorPagination``.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db.models import F, Q, QuerySet
from rest_framework.response import Response

from tara_common.exceptions import TaraAPIError

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


@dataclass(frozen=True)
class Sort:
    name: str
    field: str  # model field or annotation
    descending: bool
    kind: str  # "decimal" | "datetime"


def _bad_cursor() -> TaraAPIError:
    return TaraAPIError(
        "Invalid cursor.",
        code="validation_error",
        http_status_code=400,
        details=[{"field": "cursor", "code": "invalid", "message": "Invalid cursor."}],
    )


def _encode(sort: Sort, key, row_id) -> str:
    raw = json.dumps(
        {"s": sort.name, "k": None if key is None else str(key), "i": str(row_id)},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode(sort: Sort, token: str):
    try:
        padded = token + "=" * (-len(token) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if data.get("s") != sort.name:
            raise ValueError("cursor for another sort")
        raw_key, row_id = data.get("k"), str(data["i"])
        if raw_key is None:
            key = None
        elif sort.kind == "decimal":
            key = Decimal(raw_key)
        else:
            key = datetime.fromisoformat(raw_key)
        uuid.UUID(row_id)
    except (ValueError, KeyError, TypeError, InvalidOperation, binascii.Error, AttributeError):
        raise _bad_cursor() from None
    return key, row_id


def parse_limit(raw) -> int:
    if raw in (None, ""):
        return DEFAULT_LIMIT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 0
    if not 1 <= value <= MAX_LIMIT:
        raise TaraAPIError(
            f"limit must be between 1 and {MAX_LIMIT}.",
            code="validation_error",
            http_status_code=400,
            details=[{"field": "limit", "code": "invalid", "message": "Out of range."}],
        )
    return value


def order(qs: QuerySet, sort: Sort) -> QuerySet:
    key = F(sort.field)
    pk_order = "-id" if sort.descending else "id"
    if sort.descending:
        return qs.order_by(key.desc(nulls_last=True), pk_order)
    return qs.order_by(key.asc(nulls_last=True), pk_order)


def _after(sort: Sort, key, row_id) -> Q:
    f = sort.field
    if key is None:  # already in the null tail
        return Q(**{f"{f}__isnull": True, "id__lt" if sort.descending else "id__gt": row_id})
    beyond = "lt" if sort.descending else "gt"
    return (
        Q(**{f"{f}__{beyond}": key})
        | Q(**{f: key, f"id__{beyond}": row_id})
        | Q(**{f"{f}__isnull": True})
    )


def paginate(request, qs: QuerySet, sort: Sort, serialize) -> Response:
    """One page of ``qs`` (already filtered) in ``sort`` order, as the Tara envelope."""
    limit = parse_limit(request.query_params.get("limit"))
    token = request.query_params.get("cursor")
    if token:
        key, row_id = _decode(sort, token)
        qs = qs.filter(_after(sort, key, row_id))
    rows = list(order(qs, sort)[: limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode(sort, getattr(last, sort.field), last.id)
    return Response(
        {
            "data": serialize(rows),
            "page": {"next_cursor": next_cursor, "prev_cursor": None, "has_more": has_more},
        }
    )
