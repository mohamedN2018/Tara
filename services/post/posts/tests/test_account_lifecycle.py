"""Account lifecycle consumers (identity 3C): deactivation hides the account's
posts from everyone until reactivation; deletion erases what it wrote."""

import json
import os
import uuid

import pytest
from django.urls import reverse

from posts import handlers, services
from posts.clients import Relationship
from posts.models import (
    Comment,
    OutboxEvent,
    Post,
    PostMedia,
    PostReaction,
    PostReactionCount,
    PostState,
)
from tara_events.dispatch import handlers_for
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

SCHEMAS = "/opt/tara/libs/tara_events/tara_events/schemas"


def _acct() -> str:
    return str(uuid.uuid4())


def _event(event_type: str, account_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        subject_id=account_id,
        producer="identity-service",
        payload={"account_id": account_id},
    )


@pytest.fixture(autouse=True)
def _strangers(monkeypatch):
    monkeypatch.setattr(
        "posts.services.get_relationship", lambda a, b: Relationship(are_friends=False)
    )


def _count(event_type: str, post_id) -> int:
    return OutboxEvent.objects.filter(
        event_type=event_type, payload__subject_id=str(post_id)
    ).count()


def test_deactivation_hides_posts_and_reactivation_restores_them(client_for):
    author, viewer = _acct(), _acct()
    shown = services.create_post(author, body="hello", audience="public")
    deleted = services.create_post(author, body="gone already", audience="public")
    deleted.deleted_at = deleted.created_at
    deleted.save(update_fields=["deleted_at"])
    other = services.create_post(viewer, body="mine", audience="public")
    detail = reverse("posts:post-detail", args=[shown.id])
    assert client_for(viewer).get(detail).status_code == 200

    handlers.on_account_deactivated(_event("account.deactivated", author))
    handlers.on_account_deactivated(_event("account.deactivated", author))  # idempotent
    assert client_for(viewer).get(detail).status_code == 404
    batch = client_for(viewer).post(
        reverse("posts:post-batch"), {"ids": [str(shown.id)]}, format="json"
    )
    assert str(shown.id) not in str(batch.json().get("data"))
    assert Post.objects.get(id=shown.id).state == handlers.HELD
    assert _count("post.hidden", shown.id) == 1  # feed hides it, search drops it
    assert _count("post.deleted", shown.id) == 0  # nothing irreversible downstream
    assert _count("post.hidden", deleted.id) == 0
    assert Post.objects.get(id=other.id).state == PostState.PUBLISHED

    handlers.on_account_reactivated(_event("account.reactivated", author))
    handlers.on_account_reactivated(_event("account.reactivated", author))
    assert client_for(viewer).get(detail).status_code == 200
    assert Post.objects.get(id=shown.id).state == PostState.PUBLISHED
    assert _count("post.unhidden", shown.id) == 1  # feed shows it and fans it out again
    assert _count("post.updated", shown.id) == 1  # search indexes it again
    unhidden = _payload("post.unhidden", shown.id)
    assert unhidden["audience"] == "public" and unhidden["excerpt"] == "hello"
    assert unhidden["created_at"] == shown.created_at.isoformat()
    still = Post.objects.get(id=deleted.id)
    assert still.deleted_at is not None  # a real delete is never undone
    assert _count("post.updated", deleted.id) == 0
    assert _count("post.unhidden", deleted.id) == 0


def _payload(event_type: str, post_id) -> dict:
    row = OutboxEvent.objects.get(event_type=event_type, payload__subject_id=str(post_id))
    return row.payload["payload"]


def test_hide_events_match_their_json_schemas():
    if not os.path.isdir(SCHEMAS):
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    author = _acct()
    post = services.create_post(author, body="schema", audience="friends")
    handlers.on_account_deactivated(_event("account.deactivated", author))
    handlers.on_account_reactivated(_event("account.reactivated", author))
    for name in ("post.hidden", "post.unhidden"):
        with open(f"{SCHEMAS}/{name}.v1.json", encoding="utf-8") as f:
            schema = json.load(f)
        payload = _payload(name, post.id)
        assert set(schema["required"]) <= set(payload) <= set(schema["properties"]), name


def test_with_the_flag_off_deactivation_emits_post_deleted(settings):
    """Two-release rule: until feed consumes the pair, the old events go out."""
    settings.POST_EMIT_HIDE_EVENTS = False
    author = _acct()
    post = services.create_post(author, body="old path", audience="public")
    handlers.on_account_deactivated(_event("account.deactivated", author))
    handlers.on_account_reactivated(_event("account.reactivated", author))
    assert _count("post.deleted", post.id) == 1
    assert _count("post.hidden", post.id) == _count("post.unhidden", post.id) == 0
    assert _count("post.updated", post.id) == 1


def test_a_hidden_post_restricts_its_media(monkeypatch):
    author = _acct()
    post = services.create_post(author, body="photo", audience="public")
    Post.objects.filter(id=post.id).update(state=handlers.HELD)
    calls = []
    monkeypatch.setattr(
        "posts.services.media_client.bind",
        lambda owner, post_id, ids, restricted: calls.append((owner, post_id, ids, restricted)),
    )
    PostMedia.objects.create(post=post, media_id=uuid.uuid4(), position=0)
    hidden = EventEnvelope(
        event_type="post.hidden",
        subject_id=str(post.id),
        producer="post-service",
        payload={"post_id": str(post.id), "author_id": author, "reason": "account_deactivated"},
    )
    for fn in handlers_for("post.hidden"):
        fn(hidden)
    assert calls and calls[0][0] == author and calls[0][3] is True


def test_drafts_are_left_alone(client_for):
    author = _acct()
    draft = services.create_post(author, body="later", audience="public")
    Post.objects.filter(id=draft.id).update(state=PostState.DRAFT)
    handlers.on_account_deactivated(_event("account.deactivated", author))
    handlers.on_account_reactivated(_event("account.reactivated", author))
    assert Post.objects.get(id=draft.id).state == PostState.DRAFT


def test_deletion_erases_posts_comments_and_reactions():
    gone, other = _acct(), _acct()
    mine = services.create_post(gone, body="secret #tag @someone", audience="public")
    theirs = services.create_post(other, body="theirs", audience="public")
    services.react(gone, str(theirs.id), "like")
    services.react(other, str(theirs.id), "love")
    comment = services.add_comment(gone, str(theirs.id), "my words")

    handlers.on_account_deleted(_event("account.deleted", gone))
    handlers.on_account_deleted(_event("account.deleted", gone))  # idempotent

    erased = Post.objects.get(id=mine.id)
    assert erased.body == "" and erased.deleted_at is not None
    assert not erased.hashtags.exists() and not erased.mentions.exists()
    assert _count("post.deleted", mine.id) == 1
    c = Comment.objects.get(id=comment.id)
    assert c.body == "" and c.deleted_at is not None
    assert not PostReaction.objects.filter(account_id=gone).exists()
    theirs.refresh_from_db()
    assert theirs.reaction_count == 1
    assert dict(PostReactionCount.objects.filter(post=theirs).values_list("type", "count")) == {
        "love": 1
    }
    assert theirs.body == "theirs" and theirs.deleted_at is None
