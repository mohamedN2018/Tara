"""Counters for admin's platform statistics (``GET /internal/v1/stats/``, 8.11)."""

from __future__ import annotations

from .models import Post


def count_posts() -> int:
    """Live posts: not deleted and not removed by moderators."""
    return (
        Post.objects.filter(deleted_at__isnull=True)
        .exclude(moderation_status=Post.ModerationStatus.REMOVED)
        .count()
    )


COUNTERS = {"posts": count_posts}
