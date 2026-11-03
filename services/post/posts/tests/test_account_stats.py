"""Admin's user console (8.6): one author's live posts, on the internal stats API."""

import uuid

import pytest
from django.utils import timezone

from posts.models import Post
from tara_common.auth import mint_internal_token

pytestmark = pytest.mark.django_db


def _url(account_id) -> str:
    return f"/internal/v1/stats/accounts/{account_id}/"


def test_counts_only_the_authors_live_posts(client):
    author, other = uuid.uuid4(), uuid.uuid4()
    Post.objects.create(author_id=author, body="one")
    Post.objects.create(author_id=author, body="gone", deleted_at=timezone.now())
    Post.objects.create(
        author_id=author, body="removed", moderation_status=Post.ModerationStatus.REMOVED
    )
    Post.objects.create(author_id=other, body="someone else")
    assert client.get(_url(author)).status_code == 401
    token = mint_internal_token(issuer="admin", audience="post-internal")
    resp = client.get(_url(author), HTTP_AUTHORIZATION=f"Bearer {token}")
    assert resp.status_code == 200
    assert resp.json()["data"] == {
        "service": "post",
        "account_id": str(author),
        "stats": {"posts": 1},
    }
