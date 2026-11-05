"""Profile timeline filters (plan 08, profile track): ``year``, ``media`` (photo /
album), ``tagged_id`` ("Posted by: others" and "Photos of you") and the saved
list's ``post_type`` ("Saved reels")."""

import uuid
from datetime import UTC, datetime

import pytest
from django.urls import reverse

from posts.clients import Relationship
from posts.models import BlockedPair, Post, PostMedia, PostTag, SavedCollection, SavedItem

pytestmark = pytest.mark.django_db

URL = "posts:post-create"


def _acct() -> str:
    return str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _strangers(monkeypatch):
    monkeypatch.setattr(
        "posts.services.get_relationship", lambda a, b: Relationship(are_friends=False)
    )


def _post(author, *, body="x", photos=0, kind=Post.Type.TEXT, year=None, **extra) -> Post:
    post = Post.objects.create(author_id=author, body=body, type=kind, **extra)
    for i in range(photos):
        PostMedia.objects.create(post=post, media_id=uuid.uuid4(), position=i)
    if year:
        Post.objects.filter(id=post.id).update(created_at=datetime(year, 6, 1, tzinfo=UTC))
    return post


def _ids(resp) -> set[str]:
    assert resp.status_code == 200, resp.content
    return {p["id"] for p in resp.json()["data"]}


def test_year_filter_keeps_that_year(client_for):
    author = _acct()
    old = _post(author, year=2023)
    new = _post(author, year=2025)
    client = client_for(_acct())
    assert _ids(client.get(reverse(URL), {"author_id": author, "year": 2023})) == {str(old.id)}
    assert _ids(client.get(reverse(URL), {"author_id": author, "year": "2025"})) == {str(new.id)}
    assert _ids(client.get(reverse(URL), {"author_id": author})) == {str(old.id), str(new.id)}


@pytest.mark.parametrize("year", ["abc", "1800", "99999"])
def test_bad_year_is_400(client_for, year):
    resp = client_for(_acct()).get(reverse(URL), {"author_id": _acct(), "year": year})
    assert resp.status_code == 400


def test_media_photo_and_album(client_for):
    author = _acct()
    _post(author)  # text only
    one = _post(author, photos=1, kind=Post.Type.IMAGE)
    many = _post(author, photos=3, kind=Post.Type.IMAGE)
    _post(author, photos=1, kind=Post.Type.VIDEO)  # a video is not a photo
    client = client_for(_acct())
    assert _ids(client.get(reverse(URL), {"author_id": author, "media": "photo"})) == {
        str(one.id),
        str(many.id),
    }
    assert _ids(client.get(reverse(URL), {"author_id": author, "media": "album"})) == {str(many.id)}
    assert client.get(reverse(URL), {"author_id": author, "media": "gif"}).status_code == 400


def test_tagged_lists_other_peoples_posts_that_tag_the_person(client_for):
    person, friend, other = _acct(), _acct(), _acct()
    tagged = _post(friend, photos=1, kind=Post.Type.IMAGE)
    PostTag.objects.create(post=tagged, account_id=person)
    untagged = _post(friend)
    own = _post(person)
    PostTag.objects.create(post=own, account_id=person)  # never "others"
    in_group = _post(friend, group_id=uuid.uuid4())
    PostTag.objects.create(post=in_group, account_id=person)  # stays in its group
    private = _post(other, audience="only_me")
    PostTag.objects.create(post=private, account_id=person)  # audience still applies

    found = _ids(client_for(_acct()).get(reverse(URL), {"tagged_id": person}))
    assert found == {str(tagged.id)}
    assert str(untagged.id) not in found
    photos = client_for(_acct()).get(reverse(URL), {"tagged_id": person, "media": "photo"})
    assert _ids(photos) == {str(tagged.id)}


def test_tagged_leaves_out_authors_blocked_with_the_person(client_for):
    person, blocked_author, fine = _acct(), _acct(), _acct()
    hidden = _post(blocked_author)
    PostTag.objects.create(post=hidden, account_id=person)
    shown = _post(fine)
    PostTag.objects.create(post=shown, account_id=person)
    BlockedPair.objects.create(blocker_id=person, blocked_id=blocked_author)
    assert _ids(client_for(_acct()).get(reverse(URL), {"tagged_id": person})) == {str(shown.id)}


def test_tagged_respects_the_viewers_blocks(client_for):
    person, author, viewer = _acct(), _acct(), _acct()
    post = _post(author)
    PostTag.objects.create(post=post, account_id=person)
    BlockedPair.objects.create(blocker_id=viewer, blocked_id=author)
    assert _ids(client_for(viewer).get(reverse(URL), {"tagged_id": person})) == set()


def test_tagged_id_must_be_uuid(client_for):
    resp = client_for(_acct()).get(reverse(URL), {"tagged_id": "nope"})
    assert resp.status_code == 400


def test_saved_post_type_reel_keeps_only_reels(client_for):
    me = _acct()
    reel = _post(_acct(), kind=Post.Type.REEL)
    text = _post(_acct())
    folder = SavedCollection.objects.create(owner_id=me, name="Saved", is_default=True)
    for p in (reel, text):
        SavedItem.objects.create(owner_id=me, collection=folder, item_type="post", item_id=p.id)
    client = client_for(me)
    resp = client.get(reverse("posts:saved-list"), {"post_type": "reel"})
    assert resp.status_code == 200
    assert [i["item_id"] for i in resp.json()["data"]] == [str(reel.id)]
    everything = client.get(reverse("posts:saved-list"), {"item_type": "post"})
    assert len(everything.json()["data"]) == 2
    assert client.get(reverse("posts:saved-list"), {"post_type": "poll"}).status_code == 400
    # Someone else's saves never show.
    assert (
        client_for(_acct()).get(reverse("posts:saved-list"), {"post_type": "reel"}).json()["data"]
        == []
    )
