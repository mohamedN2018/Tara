"""Batch lookups: ``POST /media/resolve/`` and ``POST /media/playback/resolve/``.

A page used to ask for each image on its own (about 200 calls for one home
load) and ran into the read limit. The batch answers with the detail payload of
every id the viewer may see, by the same rules, and leaves the others out.
"""

import uuid

import pytest
from django.urls import reverse
from django.utils import timezone

from media_app.models import MediaAsset, MediaVariant
from media_app.throttling import ResolveThrottle

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _photo(owner, **over) -> MediaAsset:
    data = {
        "owner_id": owner,
        "kind": "image",
        "mime": "image/jpeg",
        "storage_key": f"images/{owner}/{uuid.uuid4()}",
        "status": MediaAsset.Status.READY,
        "visibility": MediaAsset.Visibility.PUBLIC,
    }
    data.update(over)
    asset = MediaAsset.objects.create(**data)
    MediaVariant.objects.create(
        media=asset, kind="thumb", storage_key=f"{asset.storage_key}/thumb.jpg", width=320
    )
    return asset


def _video(owner, *, post_id=None, status=MediaAsset.Status.READY) -> MediaAsset:
    asset = MediaAsset.objects.create(
        owner_id=owner,
        kind="video",
        purpose="post",
        mime="video/mp4",
        storage_key=f"videos/{owner}/{uuid.uuid4()}",
        status=status,
        duration_ms=3000,
        post_id=post_id,
    )
    MediaVariant.objects.create(
        media=asset, kind="poster", storage_key=f"{asset.storage_key}/poster.jpg", width=640
    )
    return asset


def _resolve(client, ids):
    return client.post(reverse("media_app:resolve"), {"ids": [str(i) for i in ids]}, format="json")


def _playbacks(client, ids):
    return client.post(
        reverse("media_app:playback-resolve"), {"ids": [str(i) for i in ids]}, format="json"
    )


def test_resolve_matches_detail_and_leaves_out_what_detail_hides(client_for, post_visibility):
    owner, viewer = _acct(), _acct()
    public = _photo(owner)
    private = _photo(owner, visibility=MediaAsset.Visibility.PRIVATE)
    friends_post, other_post = uuid.uuid4(), uuid.uuid4()
    allowed = _photo(owner, restricted=True, post_id=friends_post)
    refused = _photo(owner, restricted=True, post_id=other_post)
    orphan = _photo(owner, restricted=True, post_id=None)
    deleted = _photo(owner, deleted_at=timezone.now())
    mine = _photo(viewer, visibility=MediaAsset.Visibility.PRIVATE)
    post_visibility.allow(viewer, friends_post)

    asked = [refused, mine, public, private, uuid.uuid4(), allowed, orphan, deleted, public]
    resp = _resolve(client_for(viewer), [getattr(a, "id", a) for a in asked])

    assert resp.status_code == 200
    items = resp.json()["data"]
    # Request order, duplicates once, hidden and unknown ids simply absent.
    assert [i["id"] for i in items] == [str(mine.id), str(public.id), str(allowed.id)]
    viewer_client = client_for(viewer)
    for item in items:
        detail = viewer_client.get(reverse("media_app:media-detail", args=[item["id"]]))
        assert detail.status_code == 200
        expected = detail.json()["data"]
        assert {k: v for k, v in item.items() if k not in ("url", "variants")} == {
            k: v for k, v in expected.items() if k not in ("url", "variants")
        }
        assert item["url"] and [v["kind"] for v in item["variants"]] == ["thumb"]
    for hidden in (private, refused, orphan, deleted):
        detail = viewer_client.get(reverse("media_app:media-detail", args=[hidden.id]))
        assert detail.status_code == 404


def test_post_is_asked_once_per_post(client_for, post_visibility):
    owner, viewer = _acct(), _acct()
    post_id = uuid.uuid4()
    photos = [_photo(owner, restricted=True, post_id=post_id) for _ in range(4)]
    post_visibility.allow(viewer, post_id)
    resp = _resolve(client_for(viewer), [p.id for p in photos])
    assert len(resp.json()["data"]) == 4
    assert post_visibility.calls == [(viewer, str(post_id))]


def test_owner_is_answered_without_post(client_for, post_visibility):
    owner = _acct()
    photo = _photo(owner, restricted=True, post_id=uuid.uuid4())
    assert [i["id"] for i in _resolve(client_for(owner), [photo.id]).json()["data"]] == [
        str(photo.id)
    ]
    assert post_visibility.calls == []


# A 4xx marks the surrounding atomic block for rollback (DRF's handler, with
# ATOMIC_REQUESTS); in a test that block is the test's own, so tests that go on
# querying after a 400 or a 429 run outside it.
@pytest.mark.django_db(transaction=True)
def test_resolve_validates_its_input(client_for):
    client = client_for(_acct())
    assert _resolve(client, []).json()["data"] == []
    assert _resolve(client, [uuid.uuid4() for _ in range(101)]).status_code == 400
    assert (
        client.post(reverse("media_app:resolve"), {"ids": ["nope"]}, format="json").status_code
        == 400
    )
    assert client.post(reverse("media_app:resolve"), {}, format="json").status_code == 400
    assert _resolve(client, [uuid.uuid4() for _ in range(100)]).status_code == 200


def test_resolve_needs_a_signed_in_viewer():
    from rest_framework.test import APIClient

    resp = APIClient().post(reverse("media_app:resolve"), {"ids": []}, format="json")
    assert resp.status_code == 401


# A 4xx marks the surrounding atomic block for rollback (DRF's handler, with
# ATOMIC_REQUESTS); in a test that block is the test's own, so tests that go on
# querying after a 400 or a 429 run outside it.
@pytest.mark.django_db(transaction=True)
def test_batch_lookups_have_their_own_limit(client_for, monkeypatch):
    monkeypatch.setattr(ResolveThrottle, "THROTTLE_RATES", {"media_resolve": "2/min"})
    viewer = _acct()
    photo = _photo(viewer)
    client = client_for(viewer)
    assert [_resolve(client, [photo.id]).status_code for _ in range(2)] == [200, 200]
    assert _resolve(client, [photo.id]).status_code == 429
    assert _playbacks(client, [photo.id]).status_code == 429  # one budget for both
    # Neither the single reads nor another account are touched by it.
    assert client.get(reverse("media_app:media-detail", args=[photo.id])).status_code == 200
    assert _resolve(client_for(_acct()), [photo.id]).status_code == 200


def test_playback_batch_follows_the_single_playback_rules(client_for, post_visibility):
    owner, viewer = _acct(), _acct()
    seen_post, hidden_post = uuid.uuid4(), uuid.uuid4()
    watchable = _video(owner, post_id=seen_post)
    hidden = _video(owner, post_id=hidden_post)
    composing = _video(owner)  # on no post yet: its owner's only
    processing = _video(owner, post_id=seen_post, status=MediaAsset.Status.PROCESSING)
    photo = _photo(owner)
    post_visibility.allow(viewer, seen_post)

    asked = [hidden, processing, watchable, composing, photo, uuid.uuid4()]
    ids = [getattr(a, "id", a) for a in asked]

    items = _playbacks(client_for(viewer), ids).json()["data"]
    assert [i["id"] for i in items] == [str(watchable.id)]
    assert items[0]["hls_url"].startswith(f"media/{watchable.id}/hls/master.m3u8?token=")
    assert items[0]["poster_url"]
    single = client_for(viewer).get(reverse("media_app:playback", args=[watchable.id]))
    assert single.status_code == 200
    for absent in (hidden, processing, composing, photo):
        resp = client_for(viewer).get(reverse("media_app:playback", args=[absent.id]))
        assert resp.status_code == 404

    mine = _playbacks(client_for(owner), ids).json()["data"]
    assert [(i["id"], i["status"]) for i in mine] == [
        (str(hidden.id), "ready"),
        (str(processing.id), "processing"),
        (str(watchable.id), "ready"),
        (str(composing.id), "ready"),
    ]
    assert next(i for i in mine if i["status"] == "processing")["hls_url"] is None
