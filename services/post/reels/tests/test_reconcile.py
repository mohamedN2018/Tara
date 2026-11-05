"""Reels: a video already on a normal post, and the reconcile job (roadmap 5.5)."""

import dataclasses
import io
import uuid

import pytest
from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
from posts.models import Post, PostMedia

from reels import reconcile, tasks
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


def _bound(media_stub, reel_id) -> str:
    """Media reports the reel's video attached to the reel's own post."""
    media_id = str(Reel.objects.get(pk=reel_id).media_id)
    media_stub.assets[media_id] = dataclasses.replace(media_stub.assets[media_id], post_id=reel_id)
    return media_id


def _feed(client):
    resp = client.get(reverse("reels:reel-list"))
    assert resp.status_code == 200, resp.content
    return [item["id"] for item in resp.json()["data"]]


def _state(reel_id) -> str:
    return Reel.objects.get(pk=reel_id).publish_state


# ---- eligibility: a video already on a normal post --------------------------------


def test_a_video_already_on_a_normal_post_is_not_eligible(client_for, media_stub):
    author = acct()
    clip = add_video(media_stub, author)
    post = Post.objects.create(author_id=author, type=Post.Type.VIDEO, body="")
    PostMedia.objects.create(post=post, media_id=clip)
    me = client_for(author)
    data = me.post(reverse("reels:reel-eligibility"), {"media_id": clip}, format="json").json()
    assert data["data"]["eligible"] is False
    assert data["data"]["code"] == "media_already_attached"
    # Once that post is deleted the video may become a reel.
    Post.objects.filter(pk=post.pk).update(deleted_at=post.created_at)
    data = me.post(reverse("reels:reel-eligibility"), {"media_id": clip}, format="json").json()
    assert data["data"]["eligible"] is True and data["data"]["code"] is None


def test_a_video_already_a_reel_is_not_eligible(client_for, media_stub):
    author = acct()
    reel_id = _reel(client_for, media_stub, author)
    clip = str(Reel.objects.get(pk=reel_id).media_id)
    data = (
        client_for(author)
        .post(reverse("reels:reel-eligibility"), {"media_id": clip}, format="json")
        .json()["data"]
    )
    assert data["eligible"] is False and data["code"] == "media_already_attached"


# ---- reconcile ----------------------------------------------------------------------


def test_a_healthy_reel_is_left_alone(client_for, media_stub):
    reel_id = _reel(client_for, media_stub)
    _bound(media_stub, reel_id)
    binds = len(media_stub.binds)
    stats = reconcile.reconcile()
    assert stats == {"checked": 1, "hidden": 0, "restored": 0, "rebound": 0, "stopped": False}
    assert _state(reel_id) == PublishState.PUBLISHED
    assert Reel.objects.get(pk=reel_id).reconciled_at is not None
    assert len(media_stub.binds) == binds  # nothing bound again


def test_a_deleted_video_hides_the_reel_until_it_comes_back(client_for, media_stub):
    viewer = client_for(acct())
    reel_id = _reel(client_for, media_stub)
    media_id = _bound(media_stub, reel_id)
    assert _feed(viewer) == [reel_id]
    kept = media_stub.assets.pop(media_id)  # deleted in media

    assert reconcile.reconcile()["hidden"] == 1
    assert _state(reel_id) == PublishState.MEDIA_MISSING
    assert _feed(viewer) == []
    assert viewer.get(reverse("reels:reel-detail", args=[reel_id])).status_code == 404
    assert Post.objects.filter(pk=reel_id, deleted_at__isnull=True).exists()  # never deleted
    # Running again changes nothing.
    assert reconcile.reconcile()["hidden"] == 0

    media_stub.assets[media_id] = kept  # media recovered
    assert reconcile.reconcile()["restored"] == 1
    assert _state(reel_id) == PublishState.PUBLISHED
    assert _feed(viewer) == [reel_id]


def test_a_failed_video_hides_the_reel(client_for, media_stub):
    reel_id = _reel(client_for, media_stub)
    media_id = _bound(media_stub, reel_id)
    media_stub.assets[media_id] = dataclasses.replace(media_stub.assets[media_id], status="failed")
    assert reconcile.reconcile()["hidden"] == 1
    assert _state(reel_id) == PublishState.MEDIA_FAILED


def test_a_video_bound_to_another_post_hides_the_reel(client_for, media_stub):
    reel_id = _reel(client_for, media_stub)
    media_id = str(Reel.objects.get(pk=reel_id).media_id)
    media_stub.assets[media_id] = dataclasses.replace(
        media_stub.assets[media_id], post_id=str(uuid.uuid4())
    )
    assert reconcile.reconcile()["hidden"] == 1
    assert _state(reel_id) == PublishState.MEDIA_ELSEWHERE


def test_an_unbound_video_is_bound_again_to_its_reel(client_for, media_stub):
    author = acct()
    public_id = _reel(client_for, media_stub, author)
    friends_id = _reel(client_for, media_stub, author, audience="friends")
    media_stub.binds.clear()  # FakeMedia never records post_id: both read as unbound
    stats = reconcile.reconcile()
    assert stats["rebound"] == 2 and stats["hidden"] == 0
    by_post = {b["post_id"]: b for b in media_stub.binds}
    assert by_post[public_id]["restricted"] is False
    assert by_post[friends_id]["restricted"] is True
    assert by_post[public_id]["owner_id"] == author
    assert {_state(public_id), _state(friends_id)} == {PublishState.PUBLISHED}


def test_an_unbound_video_media_refuses_to_bind_hides_the_reel(client_for, media_stub):
    reel_id = _reel(client_for, media_stub)
    media_stub.elsewhere.add(str(Reel.objects.get(pk=reel_id).media_id))
    assert reconcile.reconcile()["hidden"] == 1
    assert _state(reel_id) == PublishState.MEDIA_ELSEWHERE


def test_media_down_stops_the_run_without_changes(client_for, media_stub):
    reel_id = _reel(client_for, media_stub)
    media_stub.down = True
    stats = reconcile.reconcile()
    assert stats["stopped"] is True and stats["checked"] == 0
    reel = Reel.objects.get(pk=reel_id)
    assert reel.publish_state == PublishState.PUBLISHED and reel.reconciled_at is None


def test_deleted_reels_are_skipped_and_the_limit_is_kept(client_for, media_stub):
    gone = _reel(client_for, media_stub)
    Post.objects.filter(pk=gone).update(deleted_at=Post.objects.get(pk=gone).created_at)
    first, second = _reel(client_for, media_stub), _reel(client_for, media_stub)
    _bound(media_stub, first)
    _bound(media_stub, second)
    assert reconcile.reconcile(limit=1)["checked"] == 1
    assert reconcile.reconcile(limit=1)["checked"] == 1  # the one not checked yet
    assert Reel.objects.filter(reconciled_at__isnull=False).count() == 2
    assert Reel.objects.get(pk=gone).reconciled_at is None


def test_dry_run_writes_and_binds_nothing(client_for, media_stub):
    reel_id = _reel(client_for, media_stub)
    media_stub.binds.clear()
    stats = reconcile.reconcile(dry_run=True)
    assert stats["rebound"] == 1 and media_stub.binds == []
    assert Reel.objects.get(pk=reel_id).reconciled_at is None


def test_command_task_and_beat_schedule(client_for, media_stub):
    reel_id = _reel(client_for, media_stub)
    media_stub.assets.pop(str(Reel.objects.get(pk=reel_id).media_id))
    out = io.StringIO()
    call_command("reconcile_reels", "--dry-run", stdout=out)
    assert "hidden=1" in out.getvalue() and _state(reel_id) == PublishState.PUBLISHED
    assert tasks.reconcile()["hidden"] == 1
    assert _state(reel_id) == PublishState.MEDIA_MISSING
    entry = settings.CELERY_BEAT_SCHEDULE["reels-reconcile"]
    assert entry["task"] == "reels.reconcile"
