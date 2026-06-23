"""Search backend: Postgres source-of-truth (+ fallback) with optional OpenSearch.

Writes always hit Postgres (durable, rebuildable). When OpenSearch is enabled we
also index there and query it; if an OpenSearch query fails we transparently fall
back to the Postgres ILIKE query, so search degrades instead of failing
(brief §L "graceful fallback if search is unavailable").
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db.models import Q

from .models import SearchDocument

logger = logging.getLogger("tara.search.backend")


def index_document(doc_type, doc_id, *, title="", body="", owner_id=None, extra=None) -> None:
    SearchDocument.objects.update_or_create(
        doc_type=doc_type,
        doc_id=str(doc_id),
        defaults={"title": title, "body": body, "owner_id": owner_id, "extra": extra or {}},
    )
    if settings.SEARCH_USE_OPENSEARCH:
        _os_index(doc_type, doc_id, title, body, owner_id, extra)


def delete_document(doc_type, doc_id) -> None:
    SearchDocument.objects.filter(doc_type=doc_type, doc_id=str(doc_id)).delete()
    if settings.SEARCH_USE_OPENSEARCH:
        _os_delete(doc_type, doc_id)


def _serialize(doc: SearchDocument) -> dict:
    return {
        "type": doc.doc_type,
        "id": doc.doc_id,
        "title": doc.title,
        "snippet": doc.body[:160],
        "owner_id": str(doc.owner_id) if doc.owner_id else None,
    }


def _db_query(q: str, doc_type: str | None, limit: int) -> list[dict]:
    qs = SearchDocument.objects.all()
    if doc_type:
        qs = qs.filter(doc_type=doc_type)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))
    return [_serialize(d) for d in qs.order_by("-updated_at")[:limit]]


def query(q: str, *, doc_type: str | None = None, limit: int = 20) -> tuple[list[dict], bool]:
    """Return (results, degraded). degraded=True if OpenSearch was bypassed."""
    if settings.SEARCH_USE_OPENSEARCH:
        try:
            return _os_query(q, doc_type, limit), False
        except Exception:  # noqa: BLE001 - degrade to DB
            logger.warning("OpenSearch query failed; falling back to Postgres", exc_info=True)
            return _db_query(q, doc_type, limit), True
    return _db_query(q, doc_type, limit), False


def autocomplete(prefix: str, *, limit: int = 10) -> list[dict]:
    qs = SearchDocument.objects.filter(title__istartswith=prefix).order_by("title")[:limit]
    return [_serialize(d) for d in qs]


# ---- OpenSearch (optional; imported lazily) ---------------------------------


def _os_client():
    from opensearchpy import OpenSearch

    return OpenSearch(hosts=[settings.OPENSEARCH_URL])


def _os_index(doc_type, doc_id, title, body, owner_id, extra) -> None:
    try:
        _os_client().index(
            index=settings.OPENSEARCH_INDEX,
            id=f"{doc_type}:{doc_id}",
            body={
                "doc_type": doc_type,
                "doc_id": str(doc_id),
                "title": title,
                "body": body,
                "owner_id": str(owner_id) if owner_id else None,
            },
        )
    except Exception:  # noqa: BLE001 - Postgres remains the source of truth
        logger.warning("OpenSearch index failed; Postgres copy retained", exc_info=True)


def _os_delete(doc_type, doc_id) -> None:
    try:
        _os_client().delete(
            index=settings.OPENSEARCH_INDEX, id=f"{doc_type}:{doc_id}", ignore=[404]
        )
    except Exception:  # noqa: BLE001
        logger.warning("OpenSearch delete failed", exc_info=True)


def _os_query(q: str, doc_type: str | None, limit: int) -> list[dict]:
    must = (
        [{"multi_match": {"query": q, "fields": ["title^2", "body"]}}] if q else [{"match_all": {}}]
    )
    filt = [{"term": {"doc_type": doc_type}}] if doc_type else []
    body = {"query": {"bool": {"must": must, "filter": filt}}, "size": limit}
    resp = _os_client().search(index=settings.OPENSEARCH_INDEX, body=body)
    out = []
    for hit in resp["hits"]["hits"]:
        s = hit["_source"]
        out.append(
            {
                "type": s["doc_type"],
                "id": s["doc_id"],
                "title": s.get("title", ""),
                "snippet": (s.get("body") or "")[:160],
                "owner_id": s.get("owner_id"),
            }
        )
    return out
