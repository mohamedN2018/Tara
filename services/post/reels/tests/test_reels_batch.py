"""``POST /api/v1/reels/batch/`` (intelligence WP 3.6): live reels in the
requested order; anything the viewer may not see, or that is not a live reel,
is left out exactly as ``/reels/<id>/`` answers 404."""

import pytest
from django.urls import reverse
from posts import services as post_services
from posts.models import BlockedPair, Post

from reels.models import PublishState, Reel

from .conftest import acct, add_video

pytestmark = pytest.mark.django_db


def _reel(client_for, media_stub, author=None, **data) -> str:
    author = author or acct()
    clip = add_video(media_stub, author)
    resp = client_for(author).post(
        reverse("reels:reel-list"), {"media_id": clip, **data}, format="json"
    )
    assert resp.status_code == 201, resp.content
    return resp.json()["data"]["id"]


def _batch(client, ids, **hints):
    return client.post(reverse("reels:reel-batch"), {"ids": ids, **hints}, format="json")


def _ids(resp) -> list[str]:
    assert resp.status_code == 200, resp.content
    return [item["id"] for item in resp.json()["data"]]


def test_returns_live_reels_in_the_requested_order_with_reel_fields(client_for, media_stub):
    a, b = _reel(client_for, media_stub), _reel(client_for, media_stub)
    resp = _batch(client_for(acct()), [b, a, b])
    assert _ids(resp) == [b, a]  # a repeated id comes back once
    item = resp.json()["data"][0]
    assert item["type"] == "reel" and item["reel"]["media_id"]
    assert set(item["reel"]) >= {"duration_ms", "width", "height", "view_count", "viewed_today"}


def test_leaves_out_every_reel_the_viewer_may_not_see(client_for, media_stub, graph):
    viewer, author = acct(), acct()
    public = _reel(client_for, media_stub, author)
    friends_only = _reel(client_for, media_stub, author, audience="friends")
    only_me = _reel(client_for, media_stub, author, audience="only_me")
    blocked_author = acct()
    blocked = _reel(client_for, media_stub, blocked_author)
    BlockedPair.objects.create(blocker_id=blocked_author, blocked_id=viewer)
    removed = _reel(client_for, media_stub)
    Post.objects.filter(id=removed).update(moderation_status=Post.ModerationStatus.REMOVED)
    deleted_author = acct()
    deleted = _reel(client_for, media_stub, deleted_author)
    post_services.delete_post(deleted_author, deleted)
    unplayable = _reel(client_for, media_stub)
    Reel.objects.filter(post_id=unplayable).update(publish_state=PublishState.MEDIA_MISSING)
    not_a_reel = str(post_services.create_post(acct(), body="text", audience="public").id)
    unknown = acct()

    ids = [
        public,
        friends_only,
        only_me,
        blocked,
        removed,
        deleted,
        unplayable,
        not_a_reel,
        unknown,
    ]
    assert _ids(_batch(client_for(viewer), ids)) == [public]

    # Each one matches the detail endpoint's answer.
    for reel_id in ids[1:]:
        detail = client_for(viewer).get(reverse("reels:reel-detail", args=[reel_id]))
        assert detail.status_code == 404

    graph.befriend(viewer, author)
    assert _ids(_batch(client_for(viewer), ids)) == [public, friends_only]
    # The author sees their own reels; no block stands between them and
    # ``blocked_author`` (who blocked the viewer only).
    assert _ids(_batch(client_for(author), ids)) == [public, friends_only, only_me, blocked]


def test_a_group_post_is_never_hydrated_as_a_reel(client_for, media_stub):
    reel = _reel(client_for, media_stub)
    Post.objects.filter(id=reel).update(group_id=acct())
    assert _ids(_batch(client_for(acct()), [reel])) == []


def test_needs_authentication():
    from rest_framework.test import APIClient

    resp = APIClient().post(reverse("reels:reel-batch"), {"ids": []}, format="json")
    assert resp.status_code in (401, 403)


def test_more_than_50_ids_are_refused(client_for):
    assert _batch(client_for(acct()), [acct() for _ in range(51)]).status_code == 400


def test_an_empty_batch_is_empty(client_for):
    assert _ids(_batch(client_for(acct()), [])) == []


def test_hints_never_change_the_answer(client_for, media_stub):
    reel = _reel(client_for, media_stub)
    viewer = client_for(acct())
    plain = _ids(_batch(viewer, [reel]))
    for hints in (
        {"surface": "reels", "src": "reels"},
        {"surface": "nope", "src": ["x" * 500]},
        {"surface": 7, "src": {"a": 1}},
        {"surface": None, "src": ["reels", "extra"]},
    ):
        assert _ids(_batch(viewer, [reel], **hints)) == plain
