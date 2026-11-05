"""Tara Intelligence WP 2.6: "not interested" on a reel emits ``reel.hidden`` and
its undo ``reel.unhidden``, once each, with ids only."""

import pytest
from django.urls import reverse
from posts.tests.event_schema import assert_all_valid, payloads, rows

from .conftest import acct, add_video

pytestmark = pytest.mark.django_db


def _reel(client_for, media_stub, author) -> str:
    clip = add_video(media_stub, author)
    resp = client_for(author).post(reverse("reels:reel-list"), {"media_id": clip}, format="json")
    assert resp.status_code == 201, resp.content
    return resp.json()["data"]["id"]


def test_hide_and_undo_emit_once_each(client_for, media_stub):
    author, viewer = acct(), acct()
    reel_id = _reel(client_for, media_stub, author)
    me = client_for(viewer)
    url = reverse("reels:reel-hide", args=[reel_id])
    assert me.post(url).status_code == 204
    assert me.post(url).status_code == 204  # idempotent: no second event
    assert me.delete(url).status_code == 204
    assert me.delete(url).status_code == 204  # nothing to undo: no event
    ids = {"post_id": reel_id, "viewer_id": viewer, "author_id": author}
    assert payloads("reel.hidden") == [ids]
    assert payloads("reel.unhidden") == [ids]
    keys = {r.partition_key for r in rows("reel.hidden") + rows("reel.unhidden")}
    assert keys == {f"account:{viewer}"}
    assert assert_all_valid("reel.hidden") == 1
    assert assert_all_valid("reel.unhidden") == 1


def test_hiding_my_own_reel_is_refused_without_an_event(client_for, media_stub):
    author = acct()
    reel_id = _reel(client_for, media_stub, author)
    assert client_for(author).post(reverse("reels:reel-hide", args=[reel_id])).status_code == 400
    assert not rows("reel.hidden")
