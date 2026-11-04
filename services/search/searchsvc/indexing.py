"""Turn owner snapshots into search documents, newest fact wins.

Every non-post document goes through ``apply``: it locks the document's
``DocState`` row, ignores a snapshot older than the last one applied (a
tombstone is kept after a removal, and a removal wins a tie), then indexes or
removes the document. The same builders serve the event handlers and the
backfill, so both index exactly the same fields.

What may be indexed (fail closed: anything unexpected is left out):
- people: profiles whose visibility is ``public``; the city only when the
  owner's field privacy for it is public (the producer sends it only then);
- pages: published pages;
- groups: ``public`` and ``private`` groups (name, handle, category and the
  description only); hidden groups never;
- listings: active (available) listings;
- events: public, scheduled, live events (post decides through its internal
  state endpoint);
- posts and hashtags: see ``posts.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tara_events.envelope import EventEnvelope

from . import backend
from .models import DocState, SearchDocument

logger = logging.getLogger("tara.search.indexing")

INDEXED_GROUP_PRIVACY = {"public", "private"}
MAX_DESCRIPTION = 300


def when(value) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = parse_datetime(value) if value else None
        except (TypeError, ValueError):
            moment = None
    if moment is not None and timezone.is_naive(moment):
        moment = moment.replace(tzinfo=UTC)
    return moment


def occurred(e: EventEnvelope) -> datetime:
    return when(e.occurred_at) or timezone.now()


def apply(doc_type: str, doc_id: str, version: datetime, doc: dict | None) -> bool:
    """Index ``doc`` (``backend.index_document`` kwargs) or, with ``None``, remove it.

    Returns False when the snapshot is older than the state already applied.
    """
    doc_id = str(doc_id)
    live = doc is not None
    with transaction.atomic():
        state, created = DocState.objects.select_for_update().get_or_create(
            doc_type=doc_type, doc_id=doc_id, defaults={"live": live, "version_at": version}
        )
        if not created:
            if version < state.version_at or (not state.live and version == state.version_at):
                logger.info("ignored stale %s snapshot for %s", doc_type, doc_id)
                return False
            state.live, state.version_at = live, version
            state.save(update_fields=["live", "version_at"])
        if live:
            backend.index_document(doc_type, doc_id, **doc)
        else:
            backend.delete_document(doc_type, doc_id)
    return True


def _clean(value, limit: int = 300) -> str:
    return (value or "").strip()[:limit] if isinstance(value, str) else ""


# ---- builders: owner snapshot -> document kwargs (None = not searchable) --------


def person_doc(account_id: str, p: dict) -> dict | None:
    if p.get("visibility", "public") != "public":
        return None
    if p.get("searchable") is False:  # profile's discoverability flag (1.6)
        return None
    handle, name = _clean(p.get("handle"), 40), _clean(p.get("display_name"), 120)
    city = _clean(p.get("city"), 80)
    return {
        # "handle display name": the SPA's mention picker reads the handle from it.
        "title": " ".join(filter(None, [handle, name])),
        "match": f"{name} {handle}",
        "owner_id": account_id,
        "location": city,
        "extra": {
            "handle": handle,
            "display_name": name or handle,
            "avatar_media_id": p.get("avatar_media_id") or None,
            "city": city or None,
        },
    }


def page_doc(p: dict) -> dict | None:
    if p.get("status", "published") != "published" or p.get("deleted"):
        return None
    name, handle = _clean(p.get("name"), 120), _clean(p.get("handle"), 40)
    category = _clean(p.get("category"), 80)
    location = _clean(p.get("location"), 160)
    return {
        "title": name or handle,
        "body": f"{handle} {category}",
        "match": f"{name} {handle}",
        "owner_id": p.get("owner") or None,
        "category": category,
        "location": location,
        "extra": {
            "handle": handle,
            "name": name or handle,
            "category": category,
            "location": location,
            "avatar_media_id": p.get("avatar_media_id") or None,
        },
    }


def group_doc(p: dict) -> dict | None:
    if p.get("privacy") not in INDEXED_GROUP_PRIVACY:
        return None  # hidden (or unknown) groups are never searchable
    if p.get("status", "active") != "active":
        return None  # suspended by moderation, or deleted
    name, handle = _clean(p.get("name"), 120), _clean(p.get("handle"), 60)
    category = _clean(p.get("category"), 80)
    description = _clean(p.get("description"), MAX_DESCRIPTION)
    count = p.get("member_count")
    return {
        "title": name or handle,
        "body": description,
        "match": f"{name} {handle}",
        "category": category,
        "extra": {
            "handle": handle,
            "name": name or handle,
            "privacy": p["privacy"],
            "category": category,
            "description": description or None,
            "member_count": count if isinstance(count, int) else None,
        },
    }


def listing_doc(p: dict) -> dict | None:
    if p.get("status") != "active":
        return None  # drafts, pending, reserved, sold, rejected, removed, archived
    title = _clean(p.get("title"), 160)
    category = p.get("category") if isinstance(p.get("category"), str) else ""
    category_name = _clean(p.get("category_name"), 120)
    location = _clean(p.get("location"), 160)
    return {
        "title": title,
        "body": category_name,
        "match": title,
        "owner_id": p.get("seller_id") or None,
        "category": category,
        "location": location,
        "source_at": when(p.get("created_at")),
        "extra": {
            "seller_id": p.get("seller_id"),
            "price": p.get("price"),
            "sale_price": p.get("sale_price"),
            "effective_price": p.get("effective_price"),
            "price_type": p.get("price_type"),
            "currency": p.get("currency"),
            "condition": p.get("condition"),
            "location": location,
            "category": {"slug": category, "name": category_name} if category else None,
            "cover_media_id": p.get("cover_media_id"),
            "created_at": p.get("created_at"),
        },
    }


def gathering_doc(s: dict) -> dict | None:
    """``s`` is post's internal state: ``indexable`` is its own public-and-live rule."""
    if not s.get("indexable"):
        return None
    title, location = _clean(s.get("title"), 200), _clean(s.get("location"), 200)
    return {
        "title": title,
        "body": _clean(s.get("description"), MAX_DESCRIPTION),
        "match": title,
        "owner_id": s.get("host_id") or None,
        "location": location,
        "source_at": when(s.get("starts_at")),
        "extra": {
            "host_id": s.get("host_id"),
            "starts_at": s.get("starts_at"),
            "ends_at": s.get("ends_at"),
            "location_type": s.get("location_type"),
            "location": location,
            "cover_media_id": s.get("cover_media_id"),
            "going_count": s.get("going_count") or 0,
            "interested_count": s.get("interested_count") or 0,
            "status": s.get("status"),
        },
    }


def refresh_gathering_counts(gathering_id: str, p: dict, at: datetime) -> None:
    """``gathering.rsvp`` carries the new counts: update them, newest wins."""
    with transaction.atomic():
        doc = (
            SearchDocument.objects.select_for_update()
            .filter(doc_type="gathering", doc_id=str(gathering_id))
            .first()
        )
        if doc is None:
            return
        seen = when(doc.extra.get("counts_at"))
        if seen and at < seen:
            return
        doc.extra = {
            **doc.extra,
            "going_count": int(p.get("going_count") or 0),
            "interested_count": int(p.get("interested_count") or 0),
            "counts_at": at.isoformat(),
        }
        doc.save(update_fields=["extra", "updated_at"])
