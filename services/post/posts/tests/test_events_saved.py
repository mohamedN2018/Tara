"""Tara Intelligence WP 2.6: ``post.saved`` / ``post.unsaved`` (owner decision 6).

Ids only (never the collection), consumed by feed only, behind
``POST_EMIT_SAVE_EVENTS``; only a new save of a post the saver may see is
announced, and only a save really removed is un-announced.
"""

import uuid

import pytest
from django.urls import reverse

from posts import services
from posts.clients import Relationship
from posts.models import OutboxEvent, SavedItem

from .event_schema import assert_all_valid, payloads, rows

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _save(client, post_id, **body):
    return client.post(reverse("posts:post-save", args=[post_id]), body, format="json")


def _unsave(client, item_type, item_id):
    return client.delete(reverse("posts:saved-item-by-target", args=[item_type, str(item_id)]))


def test_a_new_save_emits_one_post_saved_with_ids_only(client_for):
    author, me = _acct(), _acct()
    post = services.create_post(author, body="p", audience="public")
    client = client_for(me)
    box = client.post(reverse("posts:saved-collections"), {"name": "Box"}, format="json")
    box_id = box.json()["data"]["id"]

    assert _save(client, post.id).status_code == 200
    assert _save(client, post.id, collection_id=box_id).status_code == 200  # a move: no event
    assert _save(client, post.id).status_code == 200  # already saved: no event

    [row] = rows("post.saved")
    payload = row.payload["payload"]
    assert set(payload) == {"post_id", "account_id", "author_id", "item_type", "saved_at"}
    assert payload["post_id"] == str(post.id)
    assert payload["account_id"] == me and payload["author_id"] == author
    assert payload["item_type"] == "post"
    assert box_id not in str(row.payload)  # neither the collection id nor its name
    assert "Box" not in str(row.payload)
    assert row.partition_key == f"account:{me}"
    assert row.payload["actor_id"] == me
    assert assert_all_valid("post.saved") == 1


def test_unsave_emits_post_unsaved_once(client_for):
    me = _acct()
    post = services.create_post(_acct(), body="p", audience="public")
    client = client_for(me)
    _save(client, post.id)
    assert client.delete(reverse("posts:post-save", args=[post.id])).status_code == 204
    assert client.delete(reverse("posts:post-save", args=[post.id])).status_code == 204
    assert len(payloads("post.unsaved")) == 1
    assert payloads("post.unsaved")[0]["account_id"] == me
    assert assert_all_valid("post.unsaved") == 1


def test_a_video_saved_through_the_generic_endpoint_says_video(client_for):
    me = _acct()
    post = services.create_post(_acct(), body="clip", audience="public")
    client = client_for(me)
    resp = client.post(
        reverse("posts:saved-list"), {"item_type": "video", "item_id": str(post.id)}, format="json"
    )
    assert resp.status_code == 201
    assert _unsave(client, "video", post.id).status_code == 204
    assert [p["item_type"] for p in payloads("post.saved")] == ["video"]
    assert [p["item_type"] for p in payloads("post.unsaved")] == ["video"]
    assert_all_valid("post.saved")
    assert_all_valid("post.unsaved")


def test_pages_and_listings_never_emit(client_for):
    client = client_for(_acct())
    for kind in ("page", "listing"):
        item = str(uuid.uuid4())
        body = {"item_type": kind, "item_id": item}
        assert client.post(reverse("posts:saved-list"), body, format="json").status_code == 201
        assert _unsave(client, kind, item).status_code == 204
    assert not OutboxEvent.objects.filter(event_type__in=["post.saved", "post.unsaved"]).exists()


def test_a_post_the_saver_cannot_see_is_never_announced(client_for, monkeypatch):
    """The generic endpoint stores any id, but no event inflates a hidden post's saves."""
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    hidden = services.create_post(_acct(), body="secret", audience="friends")
    client = client_for(_acct())
    body = {"item_type": "post", "item_id": str(hidden.id)}
    assert client.post(reverse("posts:saved-list"), body, format="json").status_code == 201
    assert SavedItem.objects.filter(item_id=hidden.id).exists()
    assert not rows("post.saved")
    # An id that is no post at all: nothing either.
    body = {"item_type": "post", "item_id": str(uuid.uuid4())}
    assert client.post(reverse("posts:saved-list"), body, format="json").status_code == 201
    assert not rows("post.saved")


def test_the_flag_turns_both_events_off(client_for, settings):
    settings.POST_EMIT_SAVE_EVENTS = False
    post = services.create_post(_acct(), body="p", audience="public")
    client = client_for(_acct())
    _save(client, post.id)
    client.delete(reverse("posts:post-save", args=[post.id]))
    assert not OutboxEvent.objects.filter(event_type__in=["post.saved", "post.unsaved"]).exists()


def test_the_event_is_written_in_the_save_transaction(client_for, monkeypatch):
    """A save that fails after its row would be written leaves neither row nor event."""
    post = services.create_post(_acct(), body="p", audience="public")
    me = _acct()

    def boom(*args, **kwargs):
        raise RuntimeError("outbox down")

    monkeypatch.setattr("posts.services.events.emit", boom)
    with pytest.raises(RuntimeError):
        services.save_item(me, "post", str(post.id))
    assert not SavedItem.objects.filter(owner_id=me).exists()
