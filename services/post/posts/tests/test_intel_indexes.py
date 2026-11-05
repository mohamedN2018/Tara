"""Migration 0013 (intelligence WP 3.7, D11): the share and per-type post
indexes exist, are valid, and the video listing's query can use the partial
index."""

import uuid

import pytest
from django.db import connection

from posts import services
from posts.models import Post, Share

pytestmark = pytest.mark.django_db


def _index(name: str) -> tuple[str, bool] | None:
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_indexdef(i.indexrelid), i.indisvalid
            FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
            WHERE c.relname = %s
            """,
            [name],
        )
        return cur.fetchone()


def test_the_share_index_exists_and_is_valid():
    row = _index("share_account_idx")
    assert row is not None and row[1] is True
    assert "(account_id, created_at DESC)" in row[0]


def test_the_partial_post_index_exists_and_is_valid():
    row = _index("post_type_published_idx")
    assert row is not None and row[1] is True
    definition = row[0]
    assert "(type, created_at DESC)" in definition
    assert "group_id IS NULL" in definition and "'published'" in definition


def test_the_video_listing_uses_the_partial_index():
    author = uuid.uuid4()
    rows = [
        Post(author_id=author, body=f"p{i}", type=Post.Type.TEXT if i % 4 else Post.Type.VIDEO)
        for i in range(400)
    ]
    Post.objects.bulk_create(rows)
    with connection.cursor() as cur:
        cur.execute("ANALYZE post")
        # A tiny test table would otherwise be read sequentially.
        cur.execute("SET LOCAL enable_seqscan = off")
    qs = services.video_posts_queryset().order_by("-created_at", "-id")[:20]
    plan = qs.explain()
    assert "post_type_published_idx" in plan, plan


def test_the_share_index_serves_an_accounts_recent_shares():
    account = uuid.uuid4()
    post = Post.objects.create(author_id=uuid.uuid4(), body="x")
    Share.objects.bulk_create([Share(post=post, account_id=uuid.uuid4()) for _ in range(300)])
    Share.objects.create(post=post, account_id=account)
    with connection.cursor() as cur:
        cur.execute("ANALYZE share")
        cur.execute("SET LOCAL enable_seqscan = off")
    plan = Share.objects.filter(account_id=account).order_by("-created_at")[:20].explain()
    assert "share_account_idx" in plan, plan
