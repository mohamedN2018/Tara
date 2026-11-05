"""Saved collections and video post reads (track T4)."""

import uuid

import pytest
from django.urls import reverse

from posts import services
from posts.clients import Relationship
from posts.models import BlockedPair, OutboxEvent, Post, SavedCollection, SavedItem

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _collections(client):
    resp = client.get(reverse("posts:saved-collections"))
    assert resp.status_code == 200
    return resp.json()["data"]


def _create(client, name):
    return client.post(reverse("posts:saved-collections"), {"name": name}, format="json")


# ---- collections ---------------------------------------------------------------


def test_list_starts_with_the_default_collection(client_for):
    me = client_for(_acct())
    rows = _collections(me)
    assert len(rows) == 1
    assert rows[0]["is_default"] is True
    assert rows[0]["item_count"] == 0


def test_create_rename_delete_collection(client_for):
    owner = _acct()
    me = client_for(owner)
    created = _create(me, "  Recipes   to   try ")
    assert created.status_code == 201
    body = created.json()["data"]
    assert body["name"] == "Recipes to try"
    assert body["is_default"] is False

    renamed = me.patch(
        reverse("posts:saved-collection-detail", args=[body["id"]]), {"name": "Food"}, format="json"
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["name"] == "Food"

    rows = _collections(me)
    assert [r["name"] for r in rows][1:] == ["Food"]

    gone = me.delete(reverse("posts:saved-collection-detail", args=[body["id"]]))
    assert gone.status_code == 204
    assert len(_collections(me)) == 1


def test_blank_or_long_names_are_400(client_for):
    me = client_for(_acct())
    assert _create(me, "   ").status_code == 400
    assert _create(me, "x" * 81).status_code == 400


def test_the_default_collection_cannot_be_renamed_or_deleted(client_for):
    me = client_for(_acct())
    default = _collections(me)[0]
    url = reverse("posts:saved-collection-detail", args=[default["id"]])
    resp = me.patch(url, {"name": "Mine"}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "default_collection"
    assert me.delete(url).status_code == 400


def test_another_accounts_collection_is_404(client_for):
    owner = client_for(_acct())
    theirs = _create(owner, "Private").json()["data"]
    stranger = client_for(_acct())
    url = reverse("posts:saved-collection-detail", args=[theirs["id"]])
    assert stranger.patch(url, {"name": "Hacked"}, format="json").status_code == 404
    assert stranger.delete(url).status_code == 404
    assert SavedCollection.objects.get(id=theirs["id"]).name == "Private"
    listing = stranger.get(reverse("posts:saved-list"), {"collection_id": theirs["id"]})
    assert listing.status_code == 404


def test_save_into_and_move_between_collections(client_for):
    owner = _acct()
    me = client_for(owner)
    post = services.create_post(_acct(), body="p", audience="public")
    trips = _create(me, "Trips").json()["data"]

    saved = me.post(
        reverse("posts:post-save", args=[post.id]), {"collection_id": trips["id"]}, format="json"
    )
    assert saved.status_code == 200
    item = SavedItem.objects.get(owner_id=owner, item_id=post.id)
    assert str(item.collection_id) == trips["id"]
    assert saved.json()["data"]["collection_id"] == trips["id"]

    # Saving again without a collection keeps it where it is.
    me.post(reverse("posts:post-save", args=[post.id]))
    item.refresh_from_db()
    assert str(item.collection_id) == trips["id"]

    in_trips = me.get(reverse("posts:saved-list"), {"collection_id": trips["id"]}).json()["data"]
    assert [r["item_id"] for r in in_trips] == [str(post.id)]
    counts = {r["name"]: r["item_count"] for r in _collections(me)}
    assert counts["Trips"] == 1

    # Move it back to the default collection by its saved-item id.
    moved = me.patch(
        reverse("posts:saved-item", args=[item.id]), {"collection_id": None}, format="json"
    )
    assert moved.status_code == 200
    item.refresh_from_db()
    assert item.collection.is_default


def test_deleting_a_collection_keeps_its_items(client_for):
    owner = _acct()
    me = client_for(owner)
    post = services.create_post(_acct(), body="p", audience="public")
    box = _create(me, "Box").json()["data"]
    me.post(reverse("posts:post-save", args=[post.id]), {"collection_id": box["id"]}, format="json")
    me.delete(reverse("posts:saved-collection-detail", args=[box["id"]]))
    item = SavedItem.objects.get(owner_id=owner, item_id=post.id)
    assert item.collection.is_default


def test_moving_someone_elses_saved_item_is_404(client_for):
    owner = _acct()
    post = services.create_post(_acct(), body="p", audience="public")
    client_for(owner).post(reverse("posts:post-save", args=[post.id]))
    item = SavedItem.objects.get(owner_id=owner)
    other = client_for(_acct())
    resp = other.patch(
        reverse("posts:saved-item", args=[item.id]), {"collection_id": None}, format="json"
    )
    assert resp.status_code == 404


def test_saving_into_someone_elses_collection_is_404(client_for):
    theirs = _create(client_for(_acct()), "Theirs").json()["data"]
    post = services.create_post(_acct(), body="p", audience="public")
    me = _acct()
    resp = client_for(me).post(
        reverse("posts:post-save", args=[post.id]), {"collection_id": theirs["id"]}, format="json"
    )
    assert resp.status_code == 404
    assert not SavedItem.objects.filter(owner_id=me).exists()


def test_a_post_i_cannot_see_cannot_be_saved(client_for, monkeypatch):
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    hidden = services.create_post(_acct(), body="secret", audience="friends")
    me = _acct()
    assert client_for(me).post(reverse("posts:post-save", args=[hidden.id])).status_code == 404
    assert client_for(me).post(reverse("posts:post-save", args=[uuid.uuid4()])).status_code == 404
    assert not SavedItem.objects.filter(owner_id=me).exists()


def test_saves_emit_no_events_with_the_flag_off(client_for, settings):
    settings.POST_EMIT_SAVE_EVENTS = False  # Tara Intelligence WP 2.6: on by default
    post = services.create_post(_acct(), body="p", audience="public")
    before = OutboxEvent.objects.count()
    me = client_for(_acct())
    box = _create(me, "Box").json()["data"]
    me.post(reverse("posts:post-save", args=[post.id]), {"collection_id": box["id"]}, format="json")
    assert OutboxEvent.objects.count() == before


# ---- video posts ------------------------------------------------------------------


def _video(author, audience="public", **extra):
    post = services.create_post(author, body="clip", audience=audience)
    Post.objects.filter(id=post.id).update(type=Post.Type.VIDEO, **extra)
    return post


def test_video_posts_lists_only_visible_video_posts(client_for, monkeypatch):
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    me = _acct()
    public = _video(_acct())
    _video(_acct(), audience="friends")  # not my friend: hidden
    services.create_post(_acct(), body="text only", audience="public")
    blocked_author = _acct()
    _video(blocked_author)
    BlockedPair.objects.create(blocker_id=blocked_author, blocked_id=me)
    resp = client_for(me).get(reverse("posts:post-create"), {"type": "video"})
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["data"]]
    assert ids == [str(public.id)]
    assert resp.json()["data"][0]["type"] == "video"


def test_video_posts_by_one_author(client_for):
    author = _acct()
    mine = _video(author)
    _video(_acct())
    resp = client_for(_acct()).get(
        reverse("posts:post-create"), {"type": "video", "author_id": author}
    )
    assert [p["id"] for p in resp.json()["data"]] == [str(mine.id)]
    bad = client_for(_acct()).get(reverse("posts:post-create"), {"type": "video", "author_id": "x"})
    assert bad.status_code == 400
