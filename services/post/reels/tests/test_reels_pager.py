"""The two-phase reels pager (4b.9): views recorded between pages neither
repeat nor skip a reel, and a reel hidden from the viewer never comes back."""

import pytest
from django.urls import reverse
from posts.models import Post

from .conftest import acct
from .seeding import make_reel, watch

pytestmark = pytest.mark.django_db


def _get(client, **params) -> dict:
    resp = client.get(reverse("reels:reel-list"), params)
    assert resp.status_code == 200, resp.content
    return resp.json()


def _walk(client, me, *, limit, pages, watch_each_page=True):
    seen, cursor, fetched = [], None, 0
    for _ in range(pages):
        body = _get(client, limit=limit, **({"cursor": cursor} if cursor else {}))
        fetched += 1
        ids = [item["id"] for item in body["data"]]
        seen.extend(ids)
        if watch_each_page:  # the viewer watches what they were shown
            for reel_id in ids:
                watch(me, reel_id)
        cursor = body["page"]["next_cursor"]
        assert body["page"]["has_more"] is (cursor is not None)
        if cursor is None:
            break
    return seen, cursor, fetched


def test_five_pages_with_views_between_pages_have_no_duplicates_or_skips(client_for):
    me, author = acct(), acct()
    reels = [make_reel(author, minutes_ago=m) for m in range(1, 51)]
    watched_before = set(reels[1::4])  # 13 watched before the scroll starts
    for reel_id in watched_before:
        watch(me, reel_id, hours_ago=5)
    seen, cursor, fetched = _walk(client_for(me), me, limit=10, pages=5)
    assert fetched == 5 and cursor is None
    assert len(seen) == 50 and len(set(seen)) == 50  # 0 duplicates
    assert set(seen) == set(reels)  # 0 skips
    unwatched = [r for r in reels if r not in watched_before]
    assert seen == unwatched + [r for r in reels if r in watched_before]


def test_a_view_on_an_unserved_reel_between_pages_skips_nothing(client_for):
    me, author = acct(), acct()
    reels = [make_reel(author, minutes_ago=m) for m in range(1, 16)]
    viewer = client_for(me)
    first = _get(viewer, limit=5)
    for reel_id in reels[10:]:  # watched by link before the scroll reaches them
        watch(me, reel_id)
    seen = [i["id"] for i in first["data"]]
    cursor = first["page"]["next_cursor"]
    while cursor:
        body = _get(viewer, limit=5, cursor=cursor)
        seen.extend(i["id"] for i in body["data"])
        cursor = body["page"]["next_cursor"]
    assert seen == reels  # the snapshot keeps them in phase 1


def test_a_page_that_fills_at_the_phase_boundary_continues(client_for):
    me, author = acct(), acct()
    unwatched = [make_reel(author, minutes_ago=m) for m in range(1, 6)]
    watched = [make_reel(author, minutes_ago=m) for m in range(6, 8)]
    for reel_id in watched:
        watch(me, reel_id)
    seen, _, fetched = _walk(client_for(me), me, limit=5, pages=5, watch_each_page=False)
    assert seen == unwatched + watched and fetched == 2


def test_a_full_last_page_with_nothing_watched_ends_there(client_for):
    me, author = acct(), acct()
    only = [make_reel(author, minutes_ago=m) for m in range(1, 6)]
    body = _get(client_for(me), limit=5)
    assert [i["id"] for i in body["data"]] == only
    assert body["page"] == {"next_cursor": None, "prev_cursor": None, "has_more": False}


def test_a_reel_hidden_by_its_author_between_pages_is_gone(client_for):
    me, author = acct(), acct()
    reels = [make_reel(author, minutes_ago=m) for m in range(1, 11)]
    viewer = client_for(me)
    first = _get(viewer, limit=5)
    Post.objects.filter(pk=reels[7]).update(audience="only_me")
    body = _get(viewer, limit=5, cursor=first["page"]["next_cursor"])
    assert [i["id"] for i in body["data"]] == [r for r in reels[5:] if r != reels[7]]
