"""The activity log (settings): what the signed-in account did in post.

Owner-only by construction: every query is scoped to the caller's own rows
(their posts, comments, reactions, comment reactions, saves and poll votes),
so there is no id to guess and nothing to hide behind a 404. What the caller
acted *on* is a different matter: a row carries its target (the post, its
excerpt, its author) only while the caller may still see that post. A post
that was deleted, removed, made private or whose author blocked the caller
comes back as ``target: null``; the row itself (the caller's own action)
stays, and the client says "a post you can no longer see".

The log merges several tables, newest first, with one opaque cursor:
``(created_at, kind, id)`` of the last row sent. Every row id is a UUIDv7, and
within one kind rows are ordered by ``(-created_at, -id)``.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime

from django.db.models import Q

from tara_common.exceptions import TaraAPIError

from . import services
from .models import Comment, CommentReaction, PollVote, Post, PostReaction, PostState, SavedItem

KINDS = ("post", "comment", "reaction", "comment_reaction", "save", "vote")
EXCERPT = 140
PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


def _bad_request(message: str) -> TaraAPIError:
    return TaraAPIError(message, code="validation_error", http_status_code=400)


def encode_cursor(row: dict) -> str:
    raw = json.dumps({"ts": row["created_at"], "k": row["kind"], "id": row["id"]})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(token: str | None) -> tuple[datetime, str, uuid.UUID] | None:
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        data = json.loads(raw)
        ts = datetime.fromisoformat(data["ts"])
        kind = data["k"]
        row_id = uuid.UUID(str(data["id"]))
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise _bad_request("Invalid cursor.") from exc
    if kind not in KINDS or ts.tzinfo is None:
        raise _bad_request("Invalid cursor.")
    return ts, kind, row_id


def _after(qs, kind: str, cursor):
    """Rows of ``kind`` that come after the cursor in (-created_at, kind, -id) order."""
    if cursor is None:
        return qs
    ts, ckind, cid = cursor
    rank, crank = KINDS.index(kind), KINDS.index(ckind)
    if rank < crank:
        return qs.filter(created_at__lt=ts)
    if rank > crank:
        return qs.filter(created_at__lte=ts)
    return qs.filter(Q(created_at__lt=ts) | Q(created_at=ts, id__lt=cid))


def _sources(account_id: str) -> dict:
    """One queryset per kind, each the caller's own rows only."""
    return {
        "post": Post.objects.filter(
            author_id=account_id,
            author_type="user",
            deleted_at__isnull=True,
            state=PostState.PUBLISHED,
        ).exclude(moderation_status=Post.ModerationStatus.REMOVED),
        "comment": Comment.objects.filter(author_id=account_id, deleted_at__isnull=True)
        .exclude(moderation_status=Comment.ModerationStatus.REMOVED)
        .select_related("post"),
        "reaction": PostReaction.objects.filter(account_id=account_id).select_related("post"),
        "comment_reaction": CommentReaction.objects.filter(account_id=account_id).select_related(
            "comment", "comment__post"
        ),
        "save": SavedItem.objects.filter(owner_id=account_id),
        "vote": PollVote.objects.filter(account_id=account_id).select_related(
            "option", "poll__post"
        ),
    }


def _post_of(kind: str, obj) -> Post | None:
    if kind == "post":
        return obj
    if kind in ("comment", "reaction"):
        return obj.post
    if kind == "comment_reaction":
        return obj.comment.post
    if kind == "vote":
        return obj.poll.post
    return None  # saves: resolved separately (item_id only)


def _target(post: Post | None, visible: set) -> dict | None:
    if post is None or post.id not in visible:
        return None
    return {
        "post_id": str(post.id),
        "author_id": str(post.author_id),
        "author_type": post.author_type,
        "type": post.type,
        "excerpt": (post.body or "")[:EXCERPT],
    }


def _row(kind: str, obj, post: Post | None, visible: set) -> dict:
    row = {
        "id": str(obj.id),
        "kind": kind,
        "created_at": obj.created_at.isoformat(),
        "reaction": None,
        "text": "",
        "item_type": None,
        "item_id": None,
        "target": _target(post, visible),
    }
    if kind == "post":
        row["text"] = (obj.body or "")[:EXCERPT]
        row["item_type"] = obj.type
    elif kind == "comment":
        row["text"] = obj.body[:EXCERPT]
        row["item_id"] = str(obj.id)
    elif kind == "reaction":
        row["reaction"] = obj.type
    elif kind == "comment_reaction":
        row["reaction"] = obj.type
        live = obj.comment.deleted_at is None and (
            obj.comment.moderation_status != Comment.ModerationStatus.REMOVED
        )
        row["text"] = obj.comment.body[:EXCERPT] if live and row["target"] else ""
        if not live:
            row["target"] = None
    elif kind == "save":
        row["item_type"] = obj.item_type
        row["item_id"] = str(obj.item_id)
    elif kind == "vote":
        row["text"] = obj.option.text if row["target"] else ""
    return row


def activity(account_id: str, *, kind: str | None, cursor: str | None, limit: int) -> dict:
    """A page of the caller's activity, newest first."""
    if kind and kind not in KINDS:
        raise _bad_request("Unknown activity kind.")
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    position = decode_cursor(cursor)
    sources = _sources(account_id)
    kinds = [kind] if kind else list(KINDS)

    candidates: list[tuple[str, object]] = []
    for k in kinds:
        qs = _after(sources[k], k, position).order_by("-created_at", "-id")[: limit + 1]
        candidates.extend((k, obj) for obj in qs)
    candidates.sort(key=lambda c: (c[1].created_at, -KINDS.index(c[0]), c[1].id), reverse=True)
    page = candidates[:limit]
    has_more = len(candidates) > limit

    # Saved posts resolve by id; everything else carries its post already.
    saved_post_ids = [o.item_id for k, o in page if k == "save" and o.item_type == "post"]
    saved_posts = {p.id: p for p in Post.objects.filter(id__in=saved_post_ids)}
    posts = {}
    for k, o in page:
        p = saved_posts.get(o.item_id) if k == "save" else _post_of(k, o)
        if p is not None:
            posts[p.id] = p
    visible = {p.id for p in services.only_visible(account_id, list(posts.values()))}

    rows = []
    for k, o in page:
        post = saved_posts.get(o.item_id) if k == "save" else _post_of(k, o)
        rows.append(_row(k, o, post, visible))
    return {
        "data": rows,
        "page": {
            "next_cursor": encode_cursor(rows[-1]) if has_more and rows else None,
            "has_more": has_more,
        },
    }
