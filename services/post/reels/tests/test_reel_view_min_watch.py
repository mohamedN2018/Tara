"""Tara Intelligence WP 2.6 (D12): a reel view needs at least 1 s of play, and a
counted view emits ``reel.viewed`` (one per viewer per reel per UTC day)."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from posts.models import OutboxEvent
from posts.tests.event_schema import assert_all_valid, payloads, rows

from reels import services
from reels.models import Reel, ReelView

from .conftest import acct, add_video

pytestmark = pytest.mark.django_db


def _reel(client_for, media_stub, author, **data) -> str:
    clip = add_video(media_stub, author)
    resp = client_for(author).post(
        reverse("reels:reel-list"), {"media_id": clip, **data}, format="json"
    )
    assert resp.status_code == 201, resp.content
    return resp.json()["data"]["id"]


def _view(client, reel_id, body=None):
    return client.post(reverse("reels:reel-view", args=[reel_id]), body or {}, format="json")


def test_a_zero_second_play_is_not_a_view(client_for, media_stub):
    reel_id = _reel(client_for, media_stub, acct())
    me = client_for(acct())
    for body in (None, {"watch_ms": 0}, {"watch_ms": 999}, {"watch_ms": "999"}):
        resp = _view(me, reel_id, body)
        assert resp.status_code == 200, resp.content
        assert resp.json()["data"] == {"view_count": 0, "counted": False}
    assert not ReelView.objects.exists()
    assert Reel.objects.get(pk=reel_id).view_count == 0
    assert not rows("reel.viewed")


def test_one_second_counts_once_and_emits_reel_viewed(client_for, media_stub):
    author, viewer = acct(), acct()
    reel_id = _reel(client_for, media_stub, author)
    me = client_for(viewer)
    first = _view(me, reel_id, {"watch_ms": 1000}).json()["data"]
    assert first == {"view_count": 1, "counted": True}
    assert _view(me, reel_id, {"watch_ms": 5000}).json()["data"]["counted"] is False
    [payload] = payloads("reel.viewed")
    assert payload == {
        "post_id": reel_id,
        "viewer_id": viewer,
        "author_id": author,
        "day": timezone.now().date().isoformat(),
    }
    row = OutboxEvent.objects.get(event_type="reel.viewed")
    assert row.partition_key == f"account:{viewer}"
    # The next UTC day is a new view and a new event.
    ReelView.objects.update(day=timezone.now().date() - timedelta(days=1))
    assert _view(me, reel_id, {"watch_ms": 1200}).json()["data"]["counted"] is True
    assert len(payloads("reel.viewed")) == 2
    assert assert_all_valid("reel.viewed") == 2


def test_the_author_never_counts_or_emits(client_for, media_stub):
    author = acct()
    reel_id = _reel(client_for, media_stub, author)
    data = _view(client_for(author), reel_id, {"watch_ms": 60_000}).json()["data"]
    assert data["counted"] is False
    assert not rows("reel.viewed")


@pytest.mark.parametrize("bad", [-1, "abc", 1.5, True, 86_400_001, "12ms"])
def test_a_bad_watch_time_is_400(client_for, media_stub, bad):
    reel_id = _reel(client_for, media_stub, acct())
    resp = _view(client_for(acct()), reel_id, {"watch_ms": bad})
    assert resp.status_code == 400, resp.content
    assert not ReelView.objects.exists()


def test_a_reel_i_cannot_see_is_404_and_counts_nothing(client_for, media_stub):
    reel_id = _reel(client_for, media_stub, acct(), audience="friends")
    assert _view(client_for(acct()), reel_id, {"watch_ms": 5000}).status_code == 404
    assert not rows("reel.viewed")


def test_the_event_shares_the_view_transaction(client_for, media_stub, monkeypatch):
    reel_id = _reel(client_for, media_stub, acct())

    def boom(*args, **kwargs):
        raise RuntimeError("outbox down")

    monkeypatch.setattr("reels.services.events.emit", boom)
    with pytest.raises(RuntimeError):
        services.record_view(acct(), reel_id, 2000)
    assert not ReelView.objects.exists()
    assert Reel.objects.get(pk=reel_id).view_count == 0
