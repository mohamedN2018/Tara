"""Counters for admin's platform statistics (``GET /internal/v1/stats/``, 8.11)."""

from __future__ import annotations

from .models import Post


def count_posts() -> int:
    """Live posts: published, not deleted and not removed by moderators."""
    return (
        Post.objects.filter(deleted_at__isnull=True, state="published")
        .exclude(moderation_status=Post.ModerationStatus.REMOVED)
        .count()
    )


COUNTERS = {"posts": count_posts}


def count_posts_by(account_id) -> int:
    """One author's live posts, for admin's user console (8.6)."""
    return (
        Post.objects.filter(author_id=account_id, deleted_at__isnull=True, state="published")
        .exclude(moderation_status=Post.ModerationStatus.REMOVED)
        .count()
    )


ACCOUNT_COUNTERS = {"posts": count_posts_by}
