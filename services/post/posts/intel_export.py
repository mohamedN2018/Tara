"""Feed's Tara Intelligence backfill (WP 3.2), under ``/internal/v1/intel/export/``.

``posts/``: every published or held post (drafts and scheduled posts were never
announced), in the shape of ``post.created`` plus its current state, so feed's
``intel_content_ref`` stores a backfilled post exactly as it stores the events:

- ``removed``: a moderator removed it (post emitted ``post.deleted``);
- ``held``: its author is deactivated (post emitted ``post.hidden``);
- ``reel_state``: a reel's ``publish_state`` (``reel.state.changed``);
- ``moderation_open`` and ``open_reports``: a post under review and its reporters.

Ids, enums, hashtags and the 280-character excerpt only (feed derives the language
from it and stores no text). Never routed by the edge; an internal token for
``post-internal`` is required (``SearchExportView``).
"""

from __future__ import annotations

from django.db.models import Count
from django.urls import path

from tara_common.search_export import SearchExportView

from .models import Post, PostState

EXPORTED_STATES = (PostState.PUBLISHED, "held")  # "held": posts.handlers.HELD


def _posts():
    return (
        Post.objects.filter(deleted_at__isnull=True, state__in=EXPORTED_STATES)
        .select_related("reel")
        .prefetch_related("hashtags__hashtag", "media")
        .annotate(report_count=Count("reports"))
    )


def post_item(post: Post) -> tuple:
    reel = getattr(post, "reel", None) if post.type == Post.Type.REEL else None
    pending = post.moderation_status == Post.ModerationStatus.PENDING
    return post.id, {
        "post_id": str(post.id),
        "author_id": str(post.author_id),
        "author_type": post.author_type,
        "type": post.type,
        "audience": post.audience,
        "excerpt": post.body[:280],
        "media_ids": [str(m.media_id) for m in post.media.all()],  # ordered by position
        "hashtags": sorted(h.hashtag.tag for h in post.hashtags.all()),
        "shared_post_id": str(post.shared_post_id) if post.shared_post_id else None,
        "created_at": post.created_at.isoformat(),
        "group_id": str(post.group_id) if post.group_id else None,
        "approval_state": post.approval_state,
        "removed": post.moderation_status == Post.ModerationStatus.REMOVED,
        "held": post.state == "held",
        "reel_state": reel.publish_state if reel is not None else None,
        "moderation_open": pending,
        "open_reports": post.report_count if pending else 0,
    }


urlpatterns = [
    path(
        "export/posts/",
        SearchExportView.as_view(source=_posts, to_item=post_item),
        name="intel-export-posts",
    ),
]
