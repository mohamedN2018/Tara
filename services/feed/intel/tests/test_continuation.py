"""WP 4b.6: continuation into pools and ``caught_up``.

Under a variant that recommends (home@2b-r15), a session whose connection items end
goes on into eligible pool items: ``has_more`` stays true while they remain, and the
page holding the first of them says where in ``meta.caught_up_index``. Under the
control (home@2b) the feed ends with the connection inventory (``has_more=false``)
and the end is counted, with no index. Pool items explain as ``rec_popular`` /
``rec_fresh`` in why-this. The first page costs no SQL query more than home@2."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from feed import ranking
from feed.models import ReactionState

from intel import discovery, metrics, why

from . import variants
from . import world as w
from .helpers import ADULT_CLAIMS, client_with_claims

pytestmark = pytest.mark.django_db
ADULT = {"is_minor": False, "age_band": "25-34"}


def _ago(real: bool, **kw) -> timedelta:
    """``w.post``'s age for a post created ``kw`` before now (the real clock for
    tests that go through the view, ``w.NOW`` otherwise)."""
    base = timezone.now() if real else w.NOW
    return w.NOW - (base - timedelta(**kw))


def _world(connections, strangers, *, real=True):
    viewer = w.uid()
    for i in range(connections):
        friend = w.uid()
        w.feed_row(viewer, w.post(friend, age=_ago(real, minutes=5 + i)), friend)
    pool = []
    for i in range(strangers):
        p = w.post(w.uid(), age=_ago(real, hours=1, minutes=i))
        ReactionState.objects.create(post_id=p, reactor_id=w.uid(), active=True, occurred_at=w.NOW)
        pool.append(p)
    return viewer, pool


def _crawl(client_for, viewer):
    client = client_with_claims(viewer, **ADULT_CLAIMS)  # E9: discovery needs an adult
    pages, cursor = [], None
    while True:
        # 20 per page, as when these were written (first page 10 since WP 4c.2-B3).
        params = {"mode": "for_you", "limit": 20}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/api/v1/feed/", params).json()
        pages.append(body)
        cursor = body["page"]["next_cursor"]
        if not cursor:
            return pages


def test_r15_continues_into_pools_until_they_are_served(redis_hot, client_for, monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    variants.activate(variants.R15)
    viewer, pool = _world(10, 30)
    discovery.rebuild(variants.cfg(variants.R15))
    pages = _crawl(client_for, viewer)
    items = [i for p in pages for i in p["data"]]
    served = [i["post_id"] for i in items]
    assert len(served) == len(set(served)) == 40  # nothing repeats, nothing is left
    assert set(pool) <= set(served)
    assert all(p["page"]["has_more"] for p in pages[:-1]) and not pages[-1]["page"]["has_more"]
    # The caught-up marker: one page, at the first item after the last connection item.
    marked = [(n, p["meta"]["caught_up_index"]) for n, p in enumerate(pages)]
    hits = [(n, i) for n, i in marked if i is not None]
    assert len(hits) == 1
    n, index = hits[0]
    flat_index = sum(len(p["data"]) for p in pages[:n]) + index
    sources = [i.get("source") for i in items]
    assert all(s == "discovery" for s in sources[flat_index:])
    assert sources[flat_index - 1] != "discovery"
    for i in items:
        if i.get("source") == "discovery":
            assert i["reason"] in ("rec_popular", "rec_fresh")


def test_control_ends_with_the_connection_inventory(redis_hot, client_for, monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    variants.activate(variants.CONTROL)
    viewer, _pool = _world(10, 30)
    discovery.rebuild(variants.cfg())
    before = metrics.CAUGHT_UP._value.get()
    pages = _crawl(client_for, viewer)
    assert len(pages) == 1 and pages[0]["page"]["has_more"] is False
    data = pages[0]["data"]
    assert sum(1 for i in data if i.get("source") == "discovery") == 1  # thin: 10% of 11
    assert pages[0]["meta"]["caught_up_index"] is None
    assert metrics.CAUGHT_UP._value.get() == before + 1


def test_why_explains_a_pool_item_with_its_pool(redis_hot, client_for, monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    variants.activate(variants.R15)
    viewer, _pool = _world(3, 5)
    discovery.rebuild(variants.cfg(variants.R15))
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    body = client.get("/api/v1/feed/", {"mode": "for_you"}).json()
    recs = [i for i in body["data"] if i.get("source") == "discovery"]
    assert recs
    claims = {"sub": viewer, **ADULT}
    for item in recs:
        out = why.explain(claims, "post", item["post_id"], item["st"])
        assert out["factors"][0] == {"code": item["reason"]}
        # Without the session the pool that holds it still answers (token proof only).
        from intel import hot

        hot.hot().delete(ranking._session_key(viewer))
        out = why.explain(claims, "post", item["post_id"], item["st"])
        assert out["factors"][0]["code"] in ("rec_popular", "rec_fresh")


def test_first_page_costs_no_more_queries_than_home_v2(redis_hot):
    from intel.config import store

    viewer, _pool = _world(40, 20, real=False)
    store.activate("home", 2, reason="test")
    with CaptureQueriesContext(connection) as v2:
        ranking.first_page(viewer, 20, w.NOW, {"sub": viewer, **ADULT})
    variants.activate(variants.R15)
    discovery.rebuild(variants.cfg(variants.R15), now=w.NOW)
    with CaptureQueriesContext(connection) as r15:
        page = ranking.first_page(viewer, 20, w.NOW, {"sub": viewer, **ADULT})
    assert any(s == "discovery" for s in page.sources)
    assert len(r15.captured_queries) <= len(v2.captured_queries), (
        len(r15.captured_queries),
        len(v2.captured_queries),
    )


def test_mix_places_recommendations_at_the_share():
    from intel.ranking import home

    conn, recs = list(range(40)), [f"r{i}" for i in range(10)]
    out, cu = home.mix(conn, recs, 0.15, 0)
    assert [i for i, x in enumerate(out[:20]) if isinstance(x, str)] == [6, 13, 19]
    assert cu is None and len(out) == 40 + 6
    out, cu = home.mix(conn[:5], recs, 0.15, 100)
    assert cu == 5 + 0 and out[cu:] == recs  # no slot reached before the end: all tail
    out, cu = home.mix(conn[:5], recs, 0.30, 3)
    assert out[:6] == [0, 1, 2, "r0", 3, 4] and cu == 6 and out[cu:] == ["r1", "r2", "r3"]
    out, cu = home.mix([], recs, 0.15, 2)
    assert out == ["r0", "r1"] and cu == 0


def _one_friend_world(friend_posts, strangers):
    """One friend with many posts (no connection alternatives) and a pool of posts by
    distinct strangers (the alternatives a recommending variant may serve)."""
    viewer, friend = w.uid(), w.uid()
    for i in range(friend_posts):
        w.feed_row(viewer, w.post(friend, age=_ago(True, minutes=5 + i)), friend)
    pool = [w.post(w.uid(), age=_ago(True, hours=1, minutes=i)) for i in range(strangers)]
    return viewer, friend, pool


def test_r15_keeps_the_author_cap_with_pool_alternatives(redis_hot, client_for, monkeypatch):
    """R1 verifier (07 WP 4b.10): when one friend owns the whole connection inventory,
    a recommending variant fills the slots the cap closes with pool items instead of
    relaxing the cap; every friend post is still served, on later pages."""
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    variants.activate(variants.R15)
    # 4 friend posts and the 32 pool items one first page reads (pools.max_members):
    # 2 friend posts per page fit with 18 + 14 pool items around them.
    viewer, friend, _pool = _one_friend_world(4, 40)
    discovery.rebuild(variants.cfg(variants.R15))
    pages = _crawl(client_for, viewer)
    served = [i for p in pages for i in p["data"]]
    ids = [i["post_id"] for i in served]
    assert len(ids) == len(set(ids))
    for page in pages:
        by_friend = sum(1 for i in page["data"] if str(i["author_id"]) == friend)
        assert by_friend <= 2  # max_per_author_page of home@2b
    assert sum(1 for i in served if str(i["author_id"]) == friend) == 4  # none lost
    first = pages[0]["data"]
    recs = [i for i in first if i.get("source") == "discovery"]
    assert len(recs) >= 0.15 * len(first)
    assert all(i["reason"] in ("rec_popular", "rec_fresh") for i in recs)


def test_control_keeps_its_cap_and_does_not_fill_with_pools(redis_hot, client_for, monkeypatch):
    """The control (no continuation) keeps decision 23's 10% cap: the closed slots are
    not filled with pool items (the cap relaxes, as in home@2)."""
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    variants.activate(variants.CONTROL)
    viewer, _friend, _pool = _one_friend_world(30, 40)
    discovery.rebuild(variants.cfg())
    pages = _crawl(client_for, viewer)
    served = [i for p in pages for i in p["data"]]
    recs = sum(1 for i in served if i.get("source") == "discovery")
    assert recs <= 0.10 * len(served)
