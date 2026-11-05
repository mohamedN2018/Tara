"""Fast fixtures for the 4b.9 tests: reels and video posts written straight to
the tables (the create API is covered by ``test_reels.py``)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.utils import timezone
from posts.models import Post

from reels.models import Reel, ReelView


def make_reel(author: str, *, minutes_ago: int, audience: str = "public") -> str:
    """A live reel published ``minutes_ago`` (distinct times keep the order exact)."""
    at = timezone.now() - timedelta(minutes=minutes_ago)
    post = Post.objects.create(author_id=author, type=Post.Type.REEL, audience=audience)
    Post.objects.filter(pk=post.pk).update(created_at=at)
    Reel.objects.create(
        post=post,
        author_id=author,
        media_id=uuid.uuid4(),
        duration_ms=15_000,
        width=720,
        height=1280,
        created_at=at,
    )
    return str(post.pk)


def watch(viewer: str, reel_id: str, *, hours_ago: float = 0) -> None:
    """A recorded view ``hours_ago`` before now."""
    at = timezone.now() - timedelta(hours=hours_ago)
    view, _ = ReelView.objects.get_or_create(reel_id=reel_id, viewer_id=viewer, day=at.date())
    ReelView.objects.filter(pk=view.pk).update(viewed_at=at)


def make_video(author: str, *, minutes_ago: int, audience: str = "public") -> str:
    at = timezone.now() - timedelta(minutes=minutes_ago)
    post = Post.objects.create(author_id=author, type=Post.Type.VIDEO, audience=audience)
    Post.objects.filter(pk=post.pk).update(created_at=at)
    return str(post.pk)
