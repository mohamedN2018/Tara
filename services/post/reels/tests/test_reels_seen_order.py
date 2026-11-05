"""Reels "seen last" (Tara Intelligence 4b.9): the for_you tab serves reels the
viewer did not watch in the window before the watched ones."""

import pytest
from django.urls import reverse
from posts.models import BlockedPair

from reels.models import ReelHide

from .conftest import acct
from .seeding import make_reel, watch

pytestmark = pytest.mark.django_db


def _page(client, **params):
    resp = client.get(reverse("reels:reel-list"), params)
    assert resp.status_code == 200, resp.content
    body = resp.json()
    return [item["id"] for item in body["data"]], body["page"]


def test_position_zero_is_never_a_reel_watched_in_the_window(client_for, settings):
    settings.REELS_SEEN_WINDOW_H = 72
    me, author = acct(), acct()
    reels = [make_reel(author, minutes_ago=m) for m in (1, 2, 3, 4)]
    watch(me, reels[0], hours_ago=1)
    watched = {reels[0]}
    viewer = client_for(me)
    for _ in range(3):  # three opens, the viewer watching the first reel each time
        ids, _ = _page(viewer)
        assert sorted(ids) == sorted(reels)
        assert ids[0] not in watched
        assert ids == [r for r in reels if r not in watched] + [r for r in reels if r in watched]
        watch(me, ids[0])
        watched.add(ids[0])
    # Everything watched: the order is plain newest first again.
    assert _page(viewer)[0] == reels


def test_a_view_older_than_the_window_does_not_count(client_for, settings):
    settings.REELS_SEEN_WINDOW_H = 72
    me, author = acct(), acct()
    a, b = make_reel(author, minutes_ago=1), make_reel(author, minutes_ago=2)
    watch(me, a, hours_ago=71)
    watch(me, b, hours_ago=73)
    assert _page(client_for(me))[0] == [b, a]  # only a's view is inside 72 h
    settings.REELS_SEEN_WINDOW_H = 70  # a shorter window: neither counts as watched
    assert _page(client_for(me))[0] == [a, b]
    settings.REELS_SEEN_WINDOW_H = 74  # a longer one: both do, newest first
    assert _page(client_for(me))[0] == [a, b]


def test_watched_reels_are_at_most_ten_percent_of_the_first_twenty(client_for):
    me, author = acct(), acct()
    reels = [make_reel(author, minutes_ago=m) for m in range(1, 61)]
    watched = set(reels[::3])  # 20 watched, 40 unwatched, interleaved
    for reel_id in watched:
        watch(me, reel_id, hours_ago=2)
    viewer = client_for(me)
    first, page = _page(viewer, limit=10)
    second, _ = _page(viewer, limit=10, cursor=page["next_cursor"])
    first_twenty = first + second
    assert len(first_twenty) == 20
    assert sum(r in watched for r in first_twenty) <= 2  # the 10% bound
    assert sum(r in watched for r in first_twenty) == 0  # measured: none


def test_watched_reels_still_come_after_the_rest(client_for):
    me, author = acct(), acct()
    a, b, c = (make_reel(author, minutes_ago=m) for m in (1, 2, 3))
    watch(me, a)
    watch(me, c)
    ids, page = _page(client_for(me))
    assert ids == [b, a, c]
    assert page == {"next_cursor": None, "prev_cursor": None, "has_more": False}


def test_own_blocked_muted_hidden_and_private_reels_stay_out(client_for, graph):
    me, muted, blocked, other = acct(), acct(), acct(), acct()
    graph.mute(me, muted)
    BlockedPair.objects.create(blocker_id=blocked, blocked_id=me)
    make_reel(me, minutes_ago=1)
    make_reel(muted, minutes_ago=2)
    make_reel(blocked, minutes_ago=3)
    hidden = make_reel(other, minutes_ago=4)
    ReelHide.objects.create(reel_id=hidden, account_id=me)
    keep = make_reel(other, minutes_ago=5)
    make_reel(other, minutes_ago=6, audience="friends")  # not a friend
    make_reel(other, minutes_ago=7, audience="only_me")
    assert _page(client_for(me))[0] == [keep]


def test_following_tab_stays_newest_first(client_for, graph):
    me, friend = acct(), acct()
    graph.befriend(me, friend)
    newest, older = make_reel(friend, minutes_ago=1), make_reel(friend, minutes_ago=2)
    watch(me, newest)
    assert _page(client_for(me), tab="following")[0] == [newest, older]


@pytest.mark.parametrize("cursor", ["not-a-cursor", "eyJwIjozfQ", "eyJwIjoxfQ"])
def test_a_garbage_cursor_is_a_bad_request(client_for, cursor):
    resp = client_for(acct()).get(reverse("reels:reel-list"), {"cursor": cursor})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"
