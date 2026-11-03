"""The unified audit trail (roadmap 8.1): recording, querying and CSV export.

Rows record who decided what about which target, never content: ``detail``
keeps only short scalar values (ids, enums, numbers) under keys the caller
names, so a payload that one day grows a free-text field cannot leak into the
log. The request id must look like one the edge mints, or it is dropped.
"""

from __future__ import annotations

import csv
import json
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

from django.conf import settings
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import AuditEntry

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_DETAIL_VALUE_MAX = 80
_DETAIL_KEYS_MAX = 12


def _as_uuid(value) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def clean_request_id(value) -> str:
    value = str(value or "").strip()
    return value if _REQUEST_ID.match(value) else ""


def _clean_scalar(value):
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:_DETAIL_VALUE_MAX]


def clean_detail(source: dict, keys: tuple[str, ...]) -> dict:
    """Copy only ``keys`` from ``source``, as short scalars (lists of them allowed)."""
    detail: dict = {}
    for key in keys[:_DETAIL_KEYS_MAX]:
        if key not in source:
            continue
        value = source[key]
        if isinstance(value, list | tuple):
            detail[key] = [_clean_scalar(v) for v in value[:_DETAIL_KEYS_MAX]]
        elif isinstance(value, dict):
            continue  # nested structures are where free text hides
        else:
            detail[key] = _clean_scalar(value)
    return detail


def record(
    action: str,
    *,
    actor_id=None,
    actor_name: str = "",
    target_type: str = "",
    target_id: str = "",
    request_id: str = "",
    detail: dict | None = None,
    occurred_at: datetime | None = None,
    source_event_id=None,
) -> AuditEntry:
    """Write one entry (call inside the decision's transaction).

    Without a valid account id the actor is the system, named by ``actor_name``
    (the producing service). A ``source_event_id`` seen before returns the
    existing row, so a redelivered event never adds a second one.
    """
    actor = _as_uuid(actor_id)
    fields = {
        "occurred_at": occurred_at or timezone.now(),
        "actor_kind": AuditEntry.ActorKind.ACCOUNT if actor else AuditEntry.ActorKind.SYSTEM,
        "actor_id": actor,
        "actor_name": (actor_name or "")[:64] if actor is None else "",
        "action": action[:64],
        "target_type": (target_type or "")[:32],
        "target_id": str(target_id or "")[:64],
        "request_id": clean_request_id(request_id),
        "detail": detail or {},
    }
    event_id = _as_uuid(source_event_id)
    if event_id is None:
        return AuditEntry.objects.create(**fields)
    entry, _ = AuditEntry.objects.get_or_create(source_event_id=event_id, defaults=fields)
    return entry


def parse_occurred_at(value) -> datetime:
    parsed = parse_datetime(str(value or "")) if value else None
    if parsed is None:
        return timezone.now()
    if timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


# ---- querying ---------------------------------------------------------------

SYSTEM_ACTOR = "system"


def filtered(filters: dict) -> QuerySet[AuditEntry]:
    """Entries matching validated filters, newest first (the keyset order)."""
    qs = AuditEntry.objects.all()
    actor = filters.get("actor")
    if actor == SYSTEM_ACTOR:
        qs = qs.filter(actor_kind=AuditEntry.ActorKind.SYSTEM)
    elif actor:
        qs = qs.filter(actor_id=actor)
    if filters.get("action"):
        qs = qs.filter(action=filters["action"])
    if filters.get("target_type"):
        qs = qs.filter(target_type=filters["target_type"])
    if filters.get("target_id"):
        qs = qs.filter(target_id=filters["target_id"])
    if filters.get("since"):
        qs = qs.filter(occurred_at__gte=filters["since"])
    if filters.get("until"):
        qs = qs.filter(occurred_at__lt=filters["until"])
    return qs.order_by("-occurred_at", "-id")


# ---- CSV export -------------------------------------------------------------

CSV_COLUMNS = (
    "occurred_at",
    "actor_kind",
    "actor_id",
    "actor_name",
    "action",
    "target_type",
    "target_id",
    "request_id",
    "detail",
)
# A cell starting with one of these is a formula in Excel, LibreOffice and
# Google Sheets (CSV injection); a leading apostrophe makes it text.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
BOM = "﻿"  # Excel reads the file as UTF-8 only with it (Arabic stays readable)
_EXPORT_BATCH = 500


def csv_safe(value) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_PREFIXES) else text


def _csv_row(entry: AuditEntry) -> list[str]:
    detail = json.dumps(entry.detail, ensure_ascii=False, sort_keys=True) if entry.detail else ""
    values = (
        entry.occurred_at.isoformat(),
        entry.actor_kind,
        entry.actor_id or "",
        entry.actor_name,
        entry.action,
        entry.target_type,
        entry.target_id,
        entry.request_id,
        detail,
    )
    return [csv_safe(v) for v in values]


class _Line:
    """A file-like that hands back what csv.writer writes (for streaming)."""

    def write(self, value: str) -> str:
        return value


def export_cap() -> int:
    return int(getattr(settings, "ADMIN_AUDIT_EXPORT_MAX_ROWS", 10_000))


def stream_csv(queryset: QuerySet[AuditEntry], cap: int) -> Iterator[str]:
    """Yield the BOM, the header and at most ``cap`` rows, walking the keyset.

    Batches are keyed on (occurred_at, id), so rows arriving during the export
    neither repeat nor shift the walk, and no batch holds a long transaction.
    """
    writer = csv.writer(_Line())
    yield BOM + writer.writerow(CSV_COLUMNS)
    sent = 0
    last: tuple | None = None
    while sent < cap:
        batch_qs = queryset
        if last is not None:
            at, pk = last
            batch_qs = batch_qs.filter(Q(occurred_at__lt=at) | Q(occurred_at=at, id__lt=pk))
        batch = list(batch_qs[: min(_EXPORT_BATCH, cap - sent)])
        if not batch:
            return
        for entry in batch:
            yield writer.writerow(_csv_row(entry))
        sent += len(batch)
        last = (batch[-1].occurred_at, batch[-1].id)
