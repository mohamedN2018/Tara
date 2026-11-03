"""Search documents -> API results, with the viewer's relationship where graph allows.

Only fields that were indexed as public are returned: a person's handle, name,
avatar and (when its field privacy is public) city; a private group's name,
category and description, never its members or posts.
"""

from __future__ import annotations

from django.db.models import Count

from . import clients
from .models import PublicPostHashtag, SearchDocument

SNIPPET = 160


def _base(doc: SearchDocument) -> dict:
    return {
        "type": doc.doc_type,
        "id": doc.doc_id,
        "title": doc.title,
        "snippet": doc.body[:SNIPPET],
        "owner_id": str(doc.owner_id) if doc.owner_id else None,
    }


def _person(doc, x: dict, rel: dict | None, viewer_id: str) -> dict:
    if doc.doc_id == str(viewer_id):
        relationship = {"state": "self", "following": False, "request_id": None}
        mutual = None
    elif rel:
        relationship = {
            "state": rel.get("state", "none"),
            "following": bool(rel.get("following")),
            "request_id": rel.get("request_id"),
        }
        mutual = rel.get("mutual_count")  # None when graph hides the friend lists
    else:
        relationship, mutual = None, None  # graph unavailable: no guesses
    return {
        "handle": x.get("handle", ""),
        "display_name": x.get("display_name", ""),
        "avatar_media_id": x.get("avatar_media_id"),
        "city": x.get("city"),
        "relationship": relationship,
        "mutual_count": mutual if isinstance(mutual, int) else None,
    }


def _page(x: dict, rel: dict | None) -> dict:
    return {
        "handle": x.get("handle", ""),
        "name": x.get("name", ""),
        "category": x.get("category", ""),
        "location": x.get("location", ""),
        "avatar_media_id": x.get("avatar_media_id"),
        "followers_count": rel.get("followers_count") if rel else None,
        "following": rel.get("following") if rel else None,
    }


def _group(x: dict) -> dict:
    return {
        "handle": x.get("handle", ""),
        "name": x.get("name", ""),
        "privacy": x.get("privacy", "public"),
        "category": x.get("category", ""),
        "description": x.get("description"),
        "member_count": x.get("member_count"),
    }


def _listing(doc, x: dict) -> dict:
    return {
        "price": x.get("price"),
        "sale_price": x.get("sale_price"),
        "effective_price": x.get("effective_price"),
        "price_type": x.get("price_type"),
        "currency": x.get("currency"),
        "condition": x.get("condition"),
        "location": x.get("location", ""),
        "category": x.get("category"),
        "cover_media_id": x.get("cover_media_id"),
        "seller_id": x.get("seller_id") or (str(doc.owner_id) if doc.owner_id else None),
        "created_at": x.get("created_at"),
    }


def _post(doc, x: dict) -> dict:
    return {
        "author_id": str(doc.owner_id) if doc.owner_id else None,
        "author_type": x.get("author_type", "user"),
        "post_type": x.get("post_type", "text"),
        "media_ids": x.get("media_ids") or [],
        "created_at": x.get("created_at"),
    }


def _gathering(x: dict) -> dict:
    return {
        key: x.get(key)
        for key in (
            "starts_at",
            "ends_at",
            "location_type",
            "location",
            "cover_media_id",
            "host_id",
            "going_count",
            "interested_count",
            "status",
        )
    }


def serialize(docs: list[SearchDocument], viewer_id: str, *, decorate: bool = True) -> list[dict]:
    """``decorate`` adds graph data (one batch call) and hashtag counts (one query)."""
    rels: dict = {}
    counts: dict = {}
    if decorate:
        users = [d.doc_id for d in docs if d.doc_type == "user" and d.doc_id != str(viewer_id)]
        pages = [d.doc_id for d in docs if d.doc_type == "page"]
        rels = clients.relationships(str(viewer_id), users, pages)
        tags = [d.doc_id for d in docs if d.doc_type == "hashtag"]
        if tags:
            counts = dict(
                PublicPostHashtag.objects.filter(tag__in=tags)
                .values("tag")
                .annotate(n=Count("id"))
                .values_list("tag", "n")
            )
    out = []
    for doc in docs:
        item, x = _base(doc), doc.extra or {}
        if doc.doc_type == "user":
            item.update(_person(doc, x, rels.get(doc.doc_id), viewer_id))
        elif doc.doc_type == "page":
            item.update(_page(x, rels.get(doc.doc_id)))
        elif doc.doc_type == "group":
            item.update(_group(x))
        elif doc.doc_type == "listing":
            item.update(_listing(doc, x))
        elif doc.doc_type == "post":
            item.update(_post(doc, x))
        elif doc.doc_type == "gathering":
            item.update(_gathering(x))
        elif doc.doc_type == "hashtag":
            item.update({"tag": doc.doc_id, "post_count": counts.get(doc.doc_id, 0)})
        out.append(item)
    return out
