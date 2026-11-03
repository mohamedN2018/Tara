"""Search backend: Postgres source-of-truth (+ fallback) with optional OpenSearch.

Writes always hit Postgres (durable, rebuildable). When OpenSearch is enabled we
also index there and query it; if an OpenSearch query fails we transparently fall
back to the Postgres ILIKE query, so search degrades instead of failing
(brief §L "graceful fallback if search is unavailable").
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Q

from .models import BlockedPair, SearchDocument

logger = logging.getLogger("tara.search.backend")


def opensearch_enabled() -> bool:
    return bool(settings.SEARCH_USE_OPENSEARCH)


def index_document(doc_type, doc_id, *, title="", body="", owner_id=None, extra=None) -> None:
    SearchDocument.objects.update_or_create(
        doc_type=doc_type,
        doc_id=str(doc_id),
        defaults={"title": title, "body": body, "owner_id": owner_id, "extra": extra or {}},
    )
    if opensearch_enabled():
        # After commit: a rolled-back handler must not leave a copy in OpenSearch.
        transaction.on_commit(lambda: _os_index(doc_type, doc_id, title, body, owner_id, extra))


def delete_document(doc_type, doc_id) -> None:
    SearchDocument.objects.filter(doc_type=doc_type, doc_id=str(doc_id)).delete()
    if opensearch_enabled():
        transaction.on_commit(lambda: _os_delete(doc_type, doc_id))


def _serialize(doc: SearchDocument) -> dict:
    return {
        "type": doc.doc_type,
        "id": doc.doc_id,
        "title": doc.title,
        "snippet": doc.body[:160],
        "owner_id": str(doc.owner_id) if doc.owner_id else None,
    }


def blocked_ids(viewer_id: str) -> set:
    return set(
        BlockedPair.objects.filter(blocker_id=viewer_id).values_list("blocked_id", flat=True)
    ) | set(BlockedPair.objects.filter(blocked_id=viewer_id).values_list("blocker_id", flat=True))


def _db_query(q: str, doc_type: str | None, limit: int, hidden: set) -> list[dict]:
    qs = SearchDocument.objects.exclude(owner_id__in=hidden)
    if doc_type:
        qs = qs.filter(doc_type=doc_type)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))
    return [_serialize(d) for d in qs.order_by("-updated_at")[:limit]]


def query(
    q: str, *, viewer_id: str, doc_type: str | None = None, limit: int = 20
) -> tuple[list[dict], bool]:
    """Return (results, degraded). degraded=True if OpenSearch was bypassed."""
    hidden = blocked_ids(viewer_id)
    if settings.SEARCH_USE_OPENSEARCH:
        try:
            hidden_ids = {str(i) for i in hidden}
            results = _os_query(q, doc_type, limit + len(hidden))
            return [r for r in results if r.get("owner_id") not in hidden_ids][:limit], False
        except Exception:  # noqa: BLE001 - degrade to DB
            logger.warning("OpenSearch query failed; falling back to Postgres", exc_info=True)
            return _db_query(q, doc_type, limit, hidden), True
    return _db_query(q, doc_type, limit, hidden), False


def autocomplete(prefix: str, *, viewer_id: str, limit: int = 10) -> list[dict]:
    qs = (
        SearchDocument.objects.filter(title__istartswith=prefix)
        .exclude(owner_id__in=blocked_ids(viewer_id))
        .order_by("title")[:limit]
    )
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


def os_doc_ids(doc_type: str, *, limit: int = 10000) -> set[str]:
    """Ids of one doc type held by OpenSearch (for reconcile jobs). Empty on failure."""
    try:
        resp = _os_client().search(
            index=settings.OPENSEARCH_INDEX,
            body={"query": {"term": {"doc_type": doc_type}}, "_source": ["doc_id"], "size": limit},
        )
    except Exception:  # noqa: BLE001 - reconcile is best-effort on the accelerator
        logger.warning("OpenSearch id listing failed", exc_info=True)
        return set()
    return {str(h["_source"]["doc_id"]) for h in resp["hits"]["hits"]}


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
