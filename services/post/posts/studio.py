"""Creator studio reads (track T8): the author's own numbers, content library
and planner calendar.

Every query is scoped to ``author_id = the signed-in account``: nobody can read
another account's studio, so there is nothing to hide behind a 404 here (an id
that is not yours is simply never in the result). Only real counters are
reported, the ones post already keeps per post (``reaction_count``,
``comment_count``, ``share_count``) plus saves from ``saved_item``; there are no
impressions or reach until a telemetry pipeline exists.

Rescheduling is not a new write: the planner uses the existing
``PATCH /posts/drafts/<id>/ {publish_at}`` (future, at most 75 days ahead).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce

from tara_common.exceptions import TaraAPIError

from .models import Comment, Post, PostState, SavedItem

# A month grid is at most six weeks; a little slack for time-zone edges.
MAX_CALENDAR_SPAN = timedelta(days=43)
MAX_CALENDAR_POSTS = 300
TOP_POSTS = 3
LIBRARY_TYPES = ("text", "image", "video", "link", "share", "poll")


def _bad_request(message: str, code: str = "validation_error") -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=400)


def _live(author_id: str):
    """The author's posts that still exist for them: not deleted, not removed."""
    return Post.objects.filter(author_id=author_id, deleted_at__isnull=True).exclude(
        moderation_status=Post.ModerationStatus.REMOVED
    )


def published_queryset(author_id: str, post_type: str | None = None):
    """The content library's "Published" tab, newest first."""
    from . import services

    qs = _live(author_id).filter(state=PostState.PUBLISHED)
    if post_type:
        if post_type not in LIBRARY_TYPES:
            raise _bad_request("Unknown post type.")
        qs = qs.filter(type=post_type)
    return services.with_detail(qs.order_by("-created_at", "-id"))


def summary(author_id: str) -> dict:
    """Lifetime totals over the author's published posts, the counts of drafts
    and scheduled posts, and the three posts with the most interactions."""
    live = _live(author_id)
    published = live.filter(state=PostState.PUBLISHED)
    totals = published.aggregate(
        posts=Count("id"),
        reactions=Coalesce(Sum("reaction_count"), 0),
        comments=Coalesce(Sum("comment_count"), 0),
        shares=Coalesce(Sum("share_count"), 0),
    )
    states = dict(
        live.filter(state__in=(PostState.DRAFT, PostState.SCHEDULED))
        .values_list("state")
        .annotate(n=Count("id"))
    )
    saves = SavedItem.objects.filter(item_type="post", item_id__in=published.values("id")).count()
    return {
        "posts": totals["posts"],
        "reactions": totals["reactions"],
        "comments": totals["comments"],
        "shares": totals["shares"],
        "saves": saves,
        "drafts": states.get(PostState.DRAFT, 0),
        "scheduled": states.get(PostState.SCHEDULED, 0),
    }


INSIGHTS_TOP_POSTS = 10


def by_type(author_id: str) -> list[dict]:
    """The studio's Insights: my live published posts per post type, with the
    reactions, comments and shares they received (only types I have used)."""
    rows = (
        _live(author_id)
        .filter(state=PostState.PUBLISHED)
        .values("type")
        .annotate(
            posts=Count("id"),
            reactions=Coalesce(Sum("reaction_count"), 0),
            comments=Coalesce(Sum("comment_count"), 0),
            shares=Coalesce(Sum("share_count"), 0),
        )
        .order_by("type")
    )
    return sorted(
        ({k: row[k] for k in ("type", "posts", "reactions", "comments", "shares")} for row in rows),
        key=lambda r: (-(r["reactions"] + r["comments"] + r["shares"]), -r["posts"], r["type"]),
    )


def top_posts(author_id: str, limit: int = TOP_POSTS) -> list[Post]:
    """Published posts with at least one interaction, most interactions first."""
    from . import services

    qs = (
        _live(author_id)
        .filter(state=PostState.PUBLISHED)
        .annotate(interactions=F("reaction_count") + F("comment_count") + F("share_count"))
        .filter(interactions__gt=0)
        .order_by("-interactions", "-created_at", "-id")
    )
    return list(services.with_detail(qs)[:limit])


def _parse(value: str | None, name: str) -> datetime:
    if not value:
        raise _bad_request(f"{name} is required.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _bad_request(f"{name} must be an ISO 8601 date-time.") from exc
    if parsed.tzinfo is None:
        raise _bad_request(f"{name} must carry a time-zone offset.")
    return parsed


def calendar(author_id: str, start: str | None, end: str | None) -> tuple[list[Post], bool]:
    """The author's scheduled posts (by ``publish_at``) and published posts (by
    ``created_at``, the publication time) in ``[start, end)``, earliest first.

    The client sends the edges of its month or week grid in the viewer's own
    time zone (with an offset); at most 43 days. Returns the posts and whether
    the list was cut at ``MAX_CALENDAR_POSTS``.
    """
    from . import services

    lo, hi = _parse(start, "from"), _parse(end, "to")
    if hi <= lo:
        raise _bad_request("to must be after from.")
    if hi - lo > MAX_CALENDAR_SPAN:
        raise _bad_request("The calendar range is at most 43 days.", "range_too_long")
    qs = (
        _live(author_id)
        .filter(
            Q(state=PostState.SCHEDULED, publish_at__gte=lo, publish_at__lt=hi)
            | Q(state=PostState.PUBLISHED, created_at__gte=lo, created_at__lt=hi)
        )
        .annotate(at=Coalesce("publish_at", "created_at"))
        .order_by("at", "id")
    )
    rows = list(services.with_detail(qs)[: MAX_CALENDAR_POSTS + 1])
    return rows[:MAX_CALENDAR_POSTS], len(rows) > MAX_CALENDAR_POSTS


def recent_comments(author_id: str):
    """The studio's Engagement list: other people's comments (roots and replies)
    on my live published posts, newest first. Deleted or removed comments, my
    own, and comments by anyone in a block with me are left out."""
    from .services import blocked_ids

    return (
        Comment.objects.filter(
            post__in=_live(author_id).filter(state=PostState.PUBLISHED),
            deleted_at__isnull=True,
        )
        .exclude(moderation_status=Comment.ModerationStatus.REMOVED)
        .exclude(author_id=author_id)
        .exclude(author_id__in=blocked_ids(author_id))
        .select_related("reply_to", "post")
        .order_by("-created_at", "-id")
    )
