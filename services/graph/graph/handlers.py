"""Event consumers for the Social Graph service."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from django.db import transaction
from django.utils.dateparse import parse_datetime

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from .models import AccountRef, PageRef

logger = logging.getLogger("tara.graph.handlers")


@on_event("account.registered")
def on_account_registered(event: EventEnvelope) -> None:
    """Track known accounts so the graph can resolve/validate targets locally."""
    AccountRef.objects.get_or_create(account_id=event.subject_id)
    logger.debug("account ref recorded", extra={"account_id": event.subject_id})


@on_event("profile.updated")
def on_profile_updated(event: EventEnvelope) -> None:
    """Keep the cached handle fresh, and copy profile's discoverability flag
    (``searchable``, roadmap 1.6) when the event carries it."""
    defaults: dict = {}
    handle = event.payload.get("handle")
    if handle:
        defaults["handle"] = handle
    searchable = event.payload.get("searchable")
    if isinstance(searchable, bool):
        defaults["searchable"] = searchable
    if defaults:
        AccountRef.objects.update_or_create(account_id=event.subject_id, defaults=defaults)


def _uuid_or_none(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def apply_page_state(page_id: str, payload: dict, occurred_at: datetime | None) -> bool:
    """Upsert the page read model from a ``page.created``/``page.updated``
    payload (or the same shape from profile's export). An older state than the
    stored one is ignored, so a redelivered event never undoes a newer edit."""
    with transaction.atomic():
        row = PageRef.objects.select_for_update().filter(page_id=page_id).first()
        if (
            row is not None
            and row.source_occurred_at
            and occurred_at
            and occurred_at <= row.source_occurred_at
        ):
            return False
        fields = {
            "handle": str(payload.get("handle") or "")[:64],
            "name": str(payload.get("name") or "")[:160],
            "category": str(payload.get("category") or "")[:80],
            "owner_id": _uuid_or_none(payload.get("owner")),
            "avatar_media_id": _uuid_or_none(payload.get("avatar_media_id")),
            "status": str(payload.get("status") or "published")[:16],
            "deleted": bool(payload.get("deleted")),
            "source_occurred_at": occurred_at,
        }
        PageRef.objects.update_or_create(page_id=page_id, defaults=fields)
    return True


@on_event("page.created")
@on_event("page.updated")
def on_page_changed(event: EventEnvelope) -> None:
    """The "Suggested pages" widget reads published, live pages from here."""
    apply_page_state(event.subject_id, event.payload, parse_datetime(event.occurred_at or ""))
