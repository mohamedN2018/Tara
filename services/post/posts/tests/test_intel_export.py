"""Tara Intelligence WP 3.2: feed's content backfill reads every announced post here."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from posts import services
from posts.models import Post, PostReport

pytestmark = pytest.mark.django_db


def acct() -> str:
    return str(uuid.uuid4())


def _client(audience="post-internal") -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "feed", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _all(client) -> dict:
    items, after = {}, None
    while True:
        params = {"limit": 2, **({"after": after} if after else {})}
        data = client.get(reverse("intel-export-posts"), params).json()["data"]
        items.update({i["id"]: i["payload"] for i in data["items"]})
        after = data["next"]
        if after is None:
            return items


def test_export_needs_an_internal_token_for_post():
    assert APIClient().get(reverse("intel-export-posts")).status_code == 401
    assert _client("graph-internal").get(reverse("intel-export-posts")).status_code == 401


def test_every_announced_post_with_its_state_and_no_body_beyond_the_excerpt():
    author = acct()
    public = services.create_post(author, body="hello #Cairo world", audience="public")
    friends = services.create_post(author, body="x" * 400, audience="friends")
    removed = services.create_post(author, body="bad", audience="public")
    Post.objects.filter(id=removed.id).update(moderation_status=Post.ModerationStatus.REMOVED)
    held = services.create_post(author, body="away", audience="public")
    Post.objects.filter(id=held.id).update(state="held")
    pending = services.create_post(author, body="look", audience="public")
    Post.objects.filter(id=pending.id).update(moderation_status=Post.ModerationStatus.PENDING)
    PostReport.objects.create(post=pending, reporter_id=acct(), reason="spam")
    PostReport.objects.create(post=pending, reporter_id=acct(), reason="spam")
    deleted = services.create_post(author, body="gone", audience="public")
    Post.objects.filter(id=deleted.id).update(deleted_at=timezone.now())
    draft = services.create_post(author, body="later", audience="public")
    Post.objects.filter(id=draft.id).update(state="draft")

    items = _all(_client())

    assert str(deleted.id) not in items and str(draft.id) not in items
    assert set(items) == {str(p.id) for p in (public, friends, removed, held, pending)}
    p = items[str(public.id)]
    assert p["author_id"] == author and p["audience"] == "public" and p["type"] == "text"
    assert p["hashtags"] == ["cairo"]
    assert p["group_id"] is None and p["approval_state"] == "approved"
    assert p["removed"] is False and p["held"] is False and p["reel_state"] is None
    assert len(items[str(friends.id)]["excerpt"]) == 280
    assert items[str(removed.id)]["removed"] is True
    assert items[str(held.id)]["held"] is True
    assert items[str(pending.id)]["moderation_open"] is True
    assert items[str(pending.id)]["open_reports"] == 2
    assert "body" not in p
