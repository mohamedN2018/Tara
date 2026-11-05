"""The only imports ``intel`` makes from the ``feed`` app (02 section 7).

Keeping them in one module makes a later split of ``intel`` into its own service
mechanical: replace these functions, not every call site.
"""

from __future__ import annotations


def post_ids_by_author(author_id) -> list[str]:
    """Every post id of ``author_id`` that feed knows (its fan-out rows)."""
    from feed.models import FeedItem

    return [
        str(p)
        for p in FeedItem.objects.filter(author_id=author_id)
        .values_list("post_id", flat=True)
        .distinct()
    ]


def connection_rows(viewer_id, limit: int, types: tuple[str, ...] | None = None) -> list[dict]:
    """The viewer's newest ``limit`` visible feed rows (``feed_recipient_idx``):
    ``[{id, post_id, author_id, reason, type, score, post_created_at}]``. ``types``
    keeps only rows whose snapshot has one of those post types (reels, videos)."""
    from feed.ranking import visible_items

    rows = visible_items(viewer_id)
    if types:
        rows = rows.filter(snapshot__type__in=list(types))
    return [
        {
            "id": str(r["id"]),
            "post_id": str(r["post_id"]),
            "author_id": str(r["author_id"]),
            "reason": r["reason"],
            "type": (r["snapshot"] or {}).get("type") or "",
            "score": r["score"],
            "post_created_at": r["post_created_at"],
        }
        for r in rows.order_by("-post_created_at", "-id").values(
            "id", "post_id", "author_id", "reason", "snapshot", "score", "post_created_at"
        )[:limit]
    ]


def feed_post_ids(viewer_id, post_ids) -> set[str]:
    """Which of ``post_ids`` already have a feed row of the viewer (any row: a pulled
    item never duplicates one, whether or not the viewer hid it)."""
    from feed.models import FeedItem

    ids = [p for p in post_ids if p]
    if not ids:
        return set()
    return {
        str(p)
        for p in FeedItem.objects.filter(recipient_id=viewer_id, post_id__in=ids).values_list(
            "post_id", flat=True
        )
    }


def follows(viewer_id, *, since=None) -> dict[str, object]:
    """``{target_id: followed_at}`` of the viewer's active follows (users and pages);
    ``since`` keeps follows newer than it."""
    from feed.models import FollowEdge

    qs = FollowEdge.objects.filter(follower_id=viewer_id, active=True)
    if since is not None:
        qs = qs.filter(occurred_at__gte=since)
    return {str(t): at for t, at in qs.values_list("target_id", "occurred_at")}


def followed_among(viewer_id, target_ids) -> set[str]:
    from feed.models import FollowEdge

    ids = [t for t in target_ids if t]
    if not ids:
        return set()
    return {
        str(t)
        for t in FollowEdge.objects.filter(
            follower_id=viewer_id, active=True, target_id__in=ids
        ).values_list("target_id", flat=True)
    }


def viewer_exclusions(viewer_id, author_ids, post_ids) -> dict[str, set[str]]:
    """Rule E5 and E8 inputs for one viewer, in four indexed queries: hidden posts,
    snoozed and muted authors, and authors the viewer said they dislike (an explicit
    ``dislike_creator`` hide, the only explicit creator dislike before phase 6)."""
    from feed import feedback
    from feed.models import PostHide, RelationshipFlag

    authors = [a for a in author_ids if a]
    posts = [p for p in post_ids if p]
    hidden = {
        str(p)
        for p in PostHide.objects.filter(account_id=viewer_id, post_id__in=posts).values_list(
            "post_id", flat=True
        )
    }
    snoozed = {
        str(a)
        for a in feedback.active_snoozes(viewer_id)
        .filter(author_id__in=authors)
        .values_list("author_id", flat=True)
    }
    muted = {
        str(a)
        for a in RelationshipFlag.objects.filter(
            actor_id=viewer_id,
            target_id__in=authors,
            kind=RelationshipFlag.Kind.MUTE,
            active=True,
        ).values_list("target_id", flat=True)
    }
    disliked = {
        str(a)
        for a in PostHide.objects.filter(
            account_id=viewer_id,
            author_id__in=authors,
            reason=PostHide.Reason.DISLIKE_CREATOR,
        ).values_list("author_id", flat=True)
    }
    return {"hidden": hidden, "snoozed": snoozed, "muted": muted, "disliked": disliked}


def author_refs(author_ids) -> dict[str, dict]:
    """``{author_id: {kind, active, searchable}}`` for the authors feed knows."""
    from feed.models import AuthorRef

    ids = [a for a in author_ids if a]
    if not ids:
        return {}
    return {
        str(r["account_id"]): r
        for r in AuthorRef.objects.filter(account_id__in=ids).values(
            "account_id", "kind", "active", "searchable"
        )
    }


def mark_page_author(page_id) -> None:
    """A page id is an author: its ``author_ref`` row says ``kind=page``."""
    from feed.models import AuthorRef

    from .readmodels import EPOCH

    AuthorRef.objects.get_or_create(
        account_id=page_id, defaults={"occurred_at": EPOCH, "kind": "page"}
    )
    AuthorRef.objects.filter(account_id=page_id).exclude(kind="page").update(kind="page")


def set_author_lifecycle(account_id, flag: str, value: bool, when) -> bool:
    """Identity's deactivation or suspension of an author (rule E6), newest-wins per
    flag. ``active`` is true only while neither flag is set."""
    from django.db import transaction
    from feed.models import AuthorRef

    from .readmodels import EPOCH

    if flag not in ("deactivated", "suspended"):
        raise ValueError(flag)
    at = f"{flag}_at"
    with transaction.atomic():
        AuthorRef.objects.get_or_create(account_id=account_id, defaults={"occurred_at": EPOCH})
        row = AuthorRef.objects.select_for_update().get(account_id=account_id)
        stored = getattr(row, at)
        if stored is not None and when < stored:
            return False
        setattr(row, flag, value)
        setattr(row, at, when)
        row.active = not (row.deactivated or row.suspended)
        row.save(update_fields=[flag, at, "active"])
        return True


def set_follow(follower_id, target_id, target_type: str, active: bool, when) -> bool:
    """feed's ``follow_edge`` (newest-wins), for the edge backfill (WP 3.2, D6)."""
    from feed import readmodels

    return readmodels.set_follow(follower_id, target_id, target_type, active, when)


def visible_feed_rows(viewer_id) -> list[tuple]:
    """``[(post_id, author_id, snapshot type, post_created_at)]`` of the viewer's own
    feed rows minus what they hid, snoozed or muted: content they were authorized
    to receive (fan-out follows post's visibility rules)."""
    from feed.ranking import visible_items

    return [
        (
            row["post_id"],
            row["author_id"],
            (row["snapshot"] or {}).get("type"),
            row["post_created_at"],
        )
        for row in visible_items(viewer_id).values(
            "post_id", "author_id", "snapshot", "post_created_at"
        )
    ]


def set_registered_at(account_id, when) -> None:
    """``account.registered``: kept once (the first time seen wins; replays change nothing)."""
    from feed.models import AuthorRef

    from .readmodels import EPOCH

    AuthorRef.objects.get_or_create(account_id=account_id, defaults={"occurred_at": EPOCH})
    AuthorRef.objects.filter(account_id=account_id, registered_at__isnull=True).update(
        registered_at=when
    )
