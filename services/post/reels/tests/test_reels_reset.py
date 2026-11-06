"""Reels after "Reset recommendations" (Tara Intelligence WP 8.4-B2).

Feed's ``feed.recommendations.reset`` makes the for_you seen order ignore the
viewer's views before ``reset_at``; the ``reel_view`` rows stay (view counts)."""

import dataclasses
import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils import timezone
from posts.handlers import on_recommendations_reset

from reels.models import ReelsReset, ReelView
from tara_events.envelope import EventEnvelope

from .conftest import acct
from .seeding import make_reel, watch

pytestmark = pytest.mark.django_db
SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")


def _page(client, **params):
    resp = client.get(reverse("reels:reel-list"), params)
    assert resp.status_code == 200, resp.content
    return [item["id"] for item in resp.json()["data"]]


def _reset(account_id: str, at=None, event_id=None):
    payload = {"account_id": account_id, "reset_at": (at or timezone.now()).isoformat()}
    if SCHEMAS.exists():
        import jsonschema

        schema = json.loads((SCHEMAS / "feed.recommendations.reset.v1.json").read_text())
        jsonschema.validate(payload, schema, format_checker=jsonschema.FormatChecker())
    envelope = EventEnvelope(
        event_type="feed.recommendations.reset",
        subject_id=account_id,
        producer="feed-service",
        payload=payload,
    )
    if event_id:
        envelope = dataclasses.replace(envelope, event_id=event_id)
    on_recommendations_reset(envelope)
    return envelope


def test_page_one_after_reset_equals_a_cold_start_page(client_for, settings):
    settings.REELS_SEEN_WINDOW_H = 72
    me, newcomer, author = acct(), acct(), acct()
    reels = [make_reel(author, minutes_ago=m) for m in (1, 2, 3, 4, 5)]
    for i, reel in enumerate(reels[:3]):
        watch(me, reel, hours_ago=2 + i)
    before = _page(client_for(me))
    assert before[:2] == reels[3:]  # the watched reels sink before the reset
    _reset(me)
    cold = _page(client_for(newcomer))
    assert _page(client_for(me)) == cold == reels
    # The rows stay: they are view counts, not preferences.
    assert ReelView.objects.filter(viewer_id=me).count() == 3


def test_views_after_the_reset_count_again(client_for, settings):
    settings.REELS_SEEN_WINDOW_H = 72
    me, author = acct(), acct()
    reels = [make_reel(author, minutes_ago=m) for m in (1, 2, 3)]
    watch(me, reels[0], hours_ago=5)
    _reset(me, at=timezone.now() - timedelta(hours=1))
    watch(me, reels[1])  # after the reset
    assert _page(client_for(me)) == [reels[0], reels[2], reels[1]]


def test_reset_keeps_the_newest_and_is_idempotent():
    me = acct()
    newer = timezone.now()
    first = _reset(me, at=newer)
    _reset(me, at=newer, event_id=first.event_id)  # redelivery
    _reset(me, at=newer - timedelta(days=1))  # an older event arriving late
    assert ReelsReset.objects.count() == 1
    assert ReelsReset.objects.get(account_id=me).reset_at == newer


def test_another_viewer_is_unaffected(client_for, settings):
    settings.REELS_SEEN_WINDOW_H = 72
    me, other, author = acct(), acct(), acct()
    reels = [make_reel(author, minutes_ago=m) for m in (1, 2)]
    watch(other, reels[0], hours_ago=1)
    _reset(me)
    assert _page(client_for(other)) == [reels[1], reels[0]]


def _hidden(account_id: str, creator_id: str, hidden: bool, at):
    from posts.handlers import on_creator_hidden

    on_creator_hidden(
        EventEnvelope(
            event_type="intel.creator.hidden",
            subject_id=account_id,
            producer="feed-service",
            payload={
                "account_id": account_id,
                "creator_id": creator_id,
                "hidden": hidden,
                "at": at.isoformat(),
            },
        )
    )


def test_hidden_creator_leaves_for_you_and_undo_restores(client_for, graph):
    """WP 7.5-B2 on reels: "Don't recommend this creator" (not a reset; kept here with
    the other feed-driven reels tests)."""
    me, hidden_one, other = acct(), acct(), acct()
    mine = [make_reel(hidden_one, minutes_ago=1), make_reel(hidden_one, minutes_ago=2)]
    keep = make_reel(other, minutes_ago=3)
    now = timezone.now()
    _hidden(me, hidden_one, True, now)
    assert _page(client_for(me)) == [keep]
    _hidden(me, hidden_one, False, now - timedelta(minutes=1))  # older undo: ignored
    assert _page(client_for(me)) == [keep]
    _hidden(me, hidden_one, False, now + timedelta(minutes=1))
    assert _page(client_for(me)) == [*mine, keep]


def test_hidden_creator_who_is_a_friend_stays(client_for, graph):
    me, friend = acct(), acct()
    reel = make_reel(friend, minutes_ago=1)
    graph.befriend(me, friend)
    _hidden(me, friend, True, timezone.now())
    assert _page(client_for(me)) == [reel]
