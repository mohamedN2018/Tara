"""Tara Intelligence WP 2.6 (D15): the reconcile job emits ``reel.state.changed``
exactly once per reel whose publish_state it changes; a dry run emits none."""

import dataclasses
import uuid

import pytest
from django.urls import reverse
from posts.tests.event_schema import assert_all_valid, payloads, rows

from reels import reconcile
from reels.models import PublishState, Reel

from .conftest import acct, add_video

pytestmark = pytest.mark.django_db


def _reel(client_for, media_stub, author=None) -> str:
    author = author or acct()
    clip = add_video(media_stub, author)
    resp = client_for(author).post(reverse("reels:reel-list"), {"media_id": clip}, format="json")
    assert resp.status_code == 201, resp.content
    return resp.json()["data"]["id"]


def _bound(media_stub, reel_id) -> str:
    media_id = str(Reel.objects.get(pk=reel_id).media_id)
    media_stub.assets[media_id] = dataclasses.replace(media_stub.assets[media_id], post_id=reel_id)
    return media_id


def test_hide_and_restore_emit_one_event_each(client_for, media_stub):
    author = acct()
    reel_id = _reel(client_for, media_stub, author)
    healthy = _reel(client_for, media_stub)
    _bound(media_stub, healthy)
    media_id = _bound(media_stub, reel_id)
    kept = media_stub.assets.pop(media_id)

    assert reconcile.reconcile()["hidden"] == 1
    assert reconcile.reconcile()["hidden"] == 0  # unchanged: no second event
    media_stub.assets[media_id] = kept
    assert reconcile.reconcile()["restored"] == 1

    assert payloads("reel.state.changed") == [
        {
            "post_id": reel_id,
            "author_id": author,
            "from_state": PublishState.PUBLISHED,
            "to_state": PublishState.MEDIA_MISSING,
        },
        {
            "post_id": reel_id,
            "author_id": author,
            "from_state": PublishState.MEDIA_MISSING,
            "to_state": PublishState.PUBLISHED,
        },
    ]
    assert {r.partition_key for r in rows("reel.state.changed")} == {f"author:{author}"}
    assert assert_all_valid("reel.state.changed") == 2


@pytest.mark.parametrize("state", [PublishState.MEDIA_FAILED, PublishState.MEDIA_ELSEWHERE])
def test_every_hidden_state_is_announced(client_for, media_stub, state):
    reel_id = _reel(client_for, media_stub)
    media_id = _bound(media_stub, reel_id)
    info = media_stub.assets[media_id]
    media_stub.assets[media_id] = (
        dataclasses.replace(info, status="failed")
        if state == PublishState.MEDIA_FAILED
        else dataclasses.replace(info, post_id=str(uuid.uuid4()))
    )
    reconcile.reconcile()
    assert [p["to_state"] for p in payloads("reel.state.changed")] == [state]
    assert_all_valid("reel.state.changed")


def test_a_dry_run_emits_nothing(client_for, media_stub):
    reel_id = _reel(client_for, media_stub)
    media_stub.assets.pop(str(Reel.objects.get(pk=reel_id).media_id))
    assert reconcile.reconcile(dry_run=True)["hidden"] == 1
    assert not rows("reel.state.changed")
    assert Reel.objects.get(pk=reel_id).publish_state == PublishState.PUBLISHED


def test_a_reel_another_run_already_moved_is_not_announced_twice(client_for, media_stub):
    """The state is re-read under a lock: a stale in-memory copy emits nothing."""
    reel_id = _reel(client_for, media_stub)
    stale = Reel.objects.get(pk=reel_id)
    Reel.objects.filter(pk=reel_id).update(publish_state=PublishState.MEDIA_MISSING)
    reconcile._save_state(stale, PublishState.MEDIA_MISSING)  # noqa: SLF001
    assert not rows("reel.state.changed")
