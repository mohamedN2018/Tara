"""Recent searches (per account, server-side) and trending hashtags."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from . import restrictions
from .backend import norm
from .engine import _visible
from .models import PublicPostHashtag, RecentSearch, SearchDocument

logger = logging.getLogger("tara.search.history")

KEEP_PER_ACCOUNT = 20
SHOW = 10
TRENDING_WINDOWS = {"day": timedelta(days=1), "week": timedelta(days=7)}
TRENDING_LIMIT = 10
RECORDABLE_TYPES = {"user", "page", "group", "post", "listing", "gathering", "hashtag"}


class NotSearchable(Exception):
    """The entity is not (or no longer) in search for this account."""


def _visible_doc(viewer_id: str, doc_type: str, doc_id: str) -> SearchDocument | None:
    qs = SearchDocument.objects.filter(doc_type=doc_type, doc_id=str(doc_id))
    return _visible(qs, viewer_id).first()


def record(
    account_id: str, *, query: str = "", doc_type: str = "", doc_id: str = ""
) -> RecentSearch:
    """Remember a typed query or an opened result; repeating one moves it to the top."""
    now = timezone.now()
    if doc_type:
        if doc_type not in RECORDABLE_TYPES or _visible_doc(account_id, doc_type, doc_id) is None:
            raise NotSearchable()
        key = {
            "kind": RecentSearch.Kind.ENTITY,
            "query_norm": "",
            "doc_type": doc_type,
            "doc_id": str(doc_id),
        }
        defaults = {"query": "", "created_at": now}
    else:
        text = " ".join(query.split())[:200]
        qn = norm(text, 200)
        if not qn:
            raise NotSearchable()
        key = {"kind": RecentSearch.Kind.QUERY, "query_norm": qn, "doc_type": "", "doc_id": ""}
        defaults = {"query": text, "created_at": now}
    with transaction.atomic():
        row, _ = RecentSearch.objects.update_or_create(
            account_id=account_id, **key, defaults=defaults
        )
        stale = RecentSearch.objects.filter(account_id=account_id).order_by("-created_at", "-id")
        stale_ids = list(stale.values_list("id", flat=True)[KEEP_PER_ACCOUNT:])
        if stale_ids:
            RecentSearch.objects.filter(id__in=stale_ids).delete()
    return row


def _entity_fields(doc: SearchDocument) -> dict:
    x = doc.extra or {}
    title = (
        {
            "user": x.get("display_name") or x.get("handle"),
            "page": x.get("name"),
            "group": x.get("name"),
            "hashtag": doc.title,
        }.get(doc.doc_type)
        or doc.title
        or doc.body[:80]
    )
    return {
        "title": title,
        "handle": x.get("handle"),
        "avatar_media_id": x.get("avatar_media_id") or x.get("cover_media_id"),
    }


def serialize_row(row: RecentSearch, doc: SearchDocument | None = None) -> dict:
    item = {
        "id": str(row.id),
        "kind": row.kind,
        "query": row.query,
        "doc_type": row.doc_type or None,
        "doc_id": row.doc_id or None,
        "title": row.query,
        "handle": None,
        "avatar_media_id": None,
        "created_at": row.created_at.isoformat(),
    }
    if doc is not None:
        item.update(_entity_fields(doc))
    return item


def recent(account_id: str) -> list[dict]:
    """The newest entries. An opened result shows only while it is still searchable
    by this account (not removed, not narrowed, no block either way)."""
    rows = list(
        RecentSearch.objects.filter(account_id=account_id).order_by("-created_at", "-id")[
            :KEEP_PER_ACCOUNT
        ]
    )
    entities = [r for r in rows if r.kind == RecentSearch.Kind.ENTITY]
    docs = {}
    if entities:
        match = Q()
        for r in entities:
            match |= Q(doc_type=r.doc_type, doc_id=r.doc_id)
        for doc in _visible(SearchDocument.objects.filter(match), account_id):
            docs[(doc.doc_type, doc.doc_id)] = doc
    out = []
    for row in rows:
        if row.kind == RecentSearch.Kind.ENTITY:
            doc = docs.get((row.doc_type, row.doc_id))
            if doc is None:
                continue
            out.append(serialize_row(row, doc))
        else:
            out.append(serialize_row(row))
        if len(out) == SHOW:
            break
    return out


def forget(account_id: str, entry_id) -> bool:
    """Delete one of the account's own entries; False when it is not theirs (or gone)."""
    return RecentSearch.objects.filter(account_id=account_id, id=entry_id).delete()[0] > 0


def clear(account_id: str) -> int:
    return RecentSearch.objects.filter(account_id=account_id).delete()[0]


def trending_window(window: str | None) -> str:
    """The window asked for; anything else is the week (as before)."""
    return window if window in TRENDING_WINDOWS else "week"


def counted(window: str = "week"):
    """Per hashtag: distinct authors and posts of public posts in the window,
    restricted and shadowed authors left out before counting. Raw counts: they
    never leave the service (``trending`` buckets them)."""
    since = timezone.now() - TRENDING_WINDOWS[trending_window(window)]
    return (
        PublicPostHashtag.objects.filter(created_at__gte=since)
        .exclude(author_id__in=restrictions.restricted_ids())
        .values("tag")
        .annotate(authors=Count("author_id", distinct=True), posts=Count("id"))
    )


def posts_floor(posts: int) -> int | None:
    """The largest count floor the number reaches, or ``None`` below the first:
    a small count is never shown (08 §3 display rules)."""
    reached = [f for f in settings.SEARCH_TRENDING_COUNT_FLOORS if posts >= f]
    return max(reached) if reached else None


def _compute(window: str) -> list[dict]:
    rows = (
        counted(window)
        .filter(authors__gte=settings.SEARCH_TRENDING_MIN_AUTHORS)
        .order_by("-authors", "-posts", "tag")[:TRENDING_LIMIT]
    )
    return [
        {"tag": r["tag"], "posts_floor": posts_floor(r["posts"]), "window": window} for r in rows
    ]


def trending(window: str | None = "week") -> list[dict]:
    """Hashtags used by the most distinct authors of public posts in the window
    (Tara Intelligence 4b.20-B3): at least ``SEARCH_TRENDING_MIN_AUTHORS``
    authors, restricted and shadowed authors not counted, and the post count
    only as ``posts_floor`` (``None`` below the first floor). Ordered by
    authors, then posts, then tag; cached ``SEARCH_TRENDING_CACHE_S`` per window.

    Built on ``PublicPostHashtag`` only, so friends-only, group and deleted posts
    never count (they never have a row).
    """
    window = trending_window(window)
    key = restrictions.trending_cache_key(window)
    try:
        hit = cache.get(key)
    except Exception:  # noqa: BLE001 - the cache is an accelerator
        hit = None
    if hit is not None:
        return hit
    data = _compute(window)
    try:
        cache.set(key, data, settings.SEARCH_TRENDING_CACHE_S)
    except Exception:  # noqa: BLE001 - answered uncached; the next read tries again
        logger.warning("trending cache write failed", exc_info=True)
    return data
