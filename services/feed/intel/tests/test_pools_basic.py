"""WP 4b.6: the Home popular / fresh pools and the recommended mix.

Rebuilds keep only items that pass the viewer-independent rules (E1, E1b, E1c, E2,
E6, E6b, E7, E11, E9b), leave synthetic authors out, cap each set and split by
language; serving runs the full eligibility filter with the viewer's claims, leaves
out what the viewer already has a feed row for, and mixes at the variant's share:
the control (home@2b) recommends nothing to a viewer with enough connection
inventory and at most 10% to a thin one (decision 23); home@2b-r15 recommends 15%.
"""

from datetime import timedelta

import pytest
from feed import ranking
from feed.models import ReactionState

from intel import discovery, hot, origin
from intel.models import SyntheticAccount

from . import variants
from . import world as w

pytestmark = pytest.mark.django_db
ADULT = {"is_minor": False, "age_band": "25-34"}


def _react(post_id, n=1, *, at=None):
    for _ in range(n):
        ReactionState.objects.create(
            post_id=post_id, reactor_id=w.uid(), active=True, occurred_at=at or w.NOW
        )


def _members(redis_hot, lang, bucket):
    key = redis_hot.make_key(hot.pool_key("home", lang, bucket))
    return [m.decode() for m in hot.raw_client().zrevrange(key, 0, -1)]


def _stranger_posts(n, *, lang="en", reactions=1, age=timedelta(hours=2)):
    out = []
    for _ in range(n):
        p = w.post(w.uid(), lang=lang, age=age)
        _react(p, reactions)
        out.append(p)
    return out


# ---- rebuild -----------------------------------------------------------------------------


def test_only_eligible_public_posts_enter_the_pools(redis_hot, settings):
    settings.INTEL_SYNTHETIC_IN_RANKING = False
    cfg = variants.cfg()
    good = w.post(w.uid())
    page = w.page(w.uid())
    by_page = w.post(page, author_type="page")
    minor = w.post(w.uid(), author_age="minor")
    unknown = w.post(w.uid(), author_age="unknown")
    no_row = w.post(w.uid(), author_age=None)
    friends_only = w.post(w.uid(), audience="friends")
    in_group = w.post(w.uid(), group=w.group(), audience="group")
    deleted = w.post(w.uid(), state="deleted")
    removed = w.post(w.uid(), moderation="removed")
    reviewed = w.post(w.uid(), moderation_open=True, moderation="pending")
    shadowed = w.uid()
    w.restrict(shadowed)
    by_shadowed = w.post(shadowed)
    gone = w.uid()
    w.author(gone, active=False)
    by_inactive = w.post(gone)
    hidden = w.uid()
    w.author(hidden, searchable=False)
    by_unsearchable = w.post(hidden)
    reel_broken = w.post(w.uid(), type="reel", reel_state="media_missing")
    seed = w.uid()
    SyntheticAccount.objects.create(account_id=seed, label="seed-test")
    origin.clear_cache()
    by_seed = w.post(seed)
    everything = [
        good, by_page, minor, unknown, no_row, friends_only, in_group, deleted, removed,
        reviewed, by_shadowed, by_inactive, by_unsearchable, reel_broken, by_seed,
    ]  # fmt: skip
    for p in everything:
        _react(p, 2)

    counts = discovery.rebuild(cfg, now=w.NOW)

    fresh, popular = _members(redis_hot, "en", "fresh"), _members(redis_hot, "en", "popular")
    assert set(fresh) == set(popular) == {good, by_page}
    assert counts["eligible"] == 2
    # Dev: synthetic authors rank only with INTEL_SYNTHETIC_IN_RANKING.
    settings.INTEL_SYNTHETIC_IN_RANKING = True
    discovery.rebuild(cfg, now=w.NOW)
    assert by_seed in _members(redis_hot, "en", "popular")


def test_sets_are_per_language_capped_and_ordered(redis_hot):
    cfg = variants.cfg(pools={"cap": 3})
    ar = _stranger_posts(2, lang="ar")
    en = [w.post(w.uid(), age=timedelta(hours=h)) for h in (1, 2, 3, 4, 5)]
    for i, p in enumerate(en):
        _react(p, 5 - i)  # newer and more engaged first
    discovery.rebuild(cfg, now=w.NOW)
    assert set(_members(redis_hot, "ar", "popular")) == set(ar)
    assert _members(redis_hot, "en", "popular") == en[:3]
    assert _members(redis_hot, "en", "fresh") == en[:3]  # freshness decay
    assert _members(redis_hot, "mixed", "fresh") == []


def test_popular_needs_engagement_and_its_window_fresh_its_age(redis_hot):
    cfg = variants.cfg()
    quiet = w.post(w.uid(), age=timedelta(hours=1))  # no engagement
    old = w.post(w.uid(), age=timedelta(days=5))
    _react(old, 3)
    ancient = w.post(w.uid(), age=timedelta(days=9))
    _react(ancient, 9)
    discovery.rebuild(cfg, now=w.NOW)
    popular, fresh = _members(redis_hot, "en", "popular"), _members(redis_hot, "en", "fresh")
    assert quiet not in popular and quiet in fresh
    assert old in popular and old not in fresh  # older than fresh.max_age_h (48)
    assert ancient not in popular  # past popular.window_d (7)


def test_a_version_without_pools_builds_nothing(redis_hot):
    from intel import config

    assert discovery.rebuild(config.for_surface("home"), now=w.NOW) is None  # home@1
    assert not discovery.retrieves(config.for_surface("home"))


def test_a_refused_write_keeps_the_old_sets(redis_hot, monkeypatch):
    cfg = variants.cfg()
    p = _stranger_posts(1)[0]
    discovery.rebuild(cfg, now=w.NOW)
    client = hot.raw_client()

    class Full:
        def pipeline(self, transaction=True):
            raise Exception("OOM command not allowed when used memory > 'maxmemory'.")

    monkeypatch.setattr(hot, "raw_client", lambda: Full())
    _stranger_posts(1)
    out = discovery.rebuild(cfg, now=w.NOW)  # no exception
    assert out["eligible"] == 2
    monkeypatch.setattr(hot, "raw_client", lambda: client)
    assert _members(redis_hot, "en", "popular") == [p]


# ---- serving -------------------------------------------------------------------------


def _viewer_with_connections(n):
    viewer = w.uid()
    friends = [w.uid() for _ in range(20)]
    for i in range(n):
        friend = friends[i % len(friends)]
        w.feed_row(viewer, w.post(friend, age=timedelta(minutes=10 + i)), friend)
    return viewer


def _page(viewer, size=20):
    return ranking.first_page(viewer, size, w.NOW, {"sub": viewer, **ADULT})


def _recs(page):
    return [s for s in page.sources if s == discovery.SOURCE]


def test_control_recommends_nothing_with_enough_connection_inventory(redis_hot):
    variants.activate(variants.CONTROL)
    viewer = _viewer_with_connections(70)
    _stranger_posts(10)
    discovery.rebuild(variants.cfg(), now=w.NOW)
    page = _page(viewer)
    assert _recs(page) == [] and len(page.items) == 20


def test_control_gives_a_thin_inventory_at_most_ten_percent(redis_hot):
    variants.activate(variants.CONTROL)
    viewer = _viewer_with_connections(30)
    _stranger_posts(10)
    discovery.rebuild(variants.cfg(), now=w.NOW)
    page = _page(viewer)
    assert len(_recs(page)) == 2 and len(page.items) == 20  # 10% of 20
    for item, source in zip(page.items, page.sources, strict=True):
        if source == discovery.SOURCE:
            assert item.reason in ("rec_popular", "rec_fresh")


def test_r15_recommends_fifteen_percent_with_rec_reasons(redis_hot):
    variants.activate(variants.R15)
    viewer = _viewer_with_connections(80)
    pool = set(_stranger_posts(12))
    discovery.rebuild(variants.cfg(variants.R15), now=w.NOW)
    page = _page(viewer)
    recs = [i for i, s in zip(page.items, page.sources, strict=True) if s == discovery.SOURCE]
    assert len(recs) == 3  # 0.15 x 20
    assert {str(i.post_id) for i in recs} <= pool
    assert all(i.reason in ("rec_popular", "rec_fresh") for i in recs)
    assert page.has_more


def test_r30_recommends_thirty_percent(redis_hot):
    variants.activate(variants.R30)
    viewer = _viewer_with_connections(80)
    _stranger_posts(12)
    discovery.rebuild(variants.cfg(variants.R30), now=w.NOW)
    assert len(_recs(_page(viewer))) == 6


def test_serving_re_checks_every_rule_and_skips_rows_the_viewer_has(redis_hot):
    variants.activate(variants.R15)
    viewer = _viewer_with_connections(40)
    blocked_author = w.uid()
    blocked = w.post(blocked_author)
    w.block(viewer, blocked_author)
    minor = w.post(w.uid(), author_age="minor")
    mine = w.post(w.uid())
    w.feed_row(viewer, mine, "00000000-0000-0000-0000-000000000001")
    ok = _stranger_posts(1)[0]
    for p in (blocked, minor, mine):
        _react(p, 3)
    cfg = variants.cfg(variants.R15)
    discovery.rebuild(cfg, now=w.NOW)
    # A minor author's post planted in a set (a stale or tampered pool) is still dropped.
    client = hot.raw_client()
    client.zadd(redis_hot.make_key(hot.pool_key("home", "en", "popular")), {minor: 99.0})
    served = set()
    cursor = None
    page = _page(viewer)
    served |= {
        str(i.post_id) for i, s in zip(page.items, page.sources, strict=True) if s == "discovery"
    }
    cursor = page.next_cursor
    while cursor:
        page = ranking.next_page(viewer, cursor, 20, {"sub": viewer, **ADULT})
        served |= {
            str(i.post_id)
            for i, s in zip(page.items, page.sources, strict=True)
            if s == "discovery"
        }
        cursor = page.next_cursor
    assert ok in served
    assert not served & {blocked, minor, mine}


def test_a_limited_viewer_gets_no_recommendations(redis_hot):
    variants.activate(variants.R15)
    viewer = _viewer_with_connections(30)
    _stranger_posts(10)
    discovery.rebuild(variants.cfg(variants.R15), now=w.NOW)
    page = ranking.first_page(viewer, 20, w.NOW, {"sub": viewer, "is_minor": True})
    assert _recs(page) == []  # E9: no allow-listed topics before phase 6


def test_home_v1_and_v2_never_read_the_pools(redis_hot, monkeypatch):
    from intel import config

    calls = []
    monkeypatch.setattr(discovery, "read", lambda cfg: calls.append(cfg) or [])
    viewer = _viewer_with_connections(5)
    _page(viewer)
    variants_v2 = config.for_version("home", 2)
    assert not discovery.retrieves(variants_v2)
    assert calls == []


def test_beat_rebuilds_only_when_due(redis_hot):
    from django.utils import timezone

    from intel import tasks

    assert tasks.rebuild_pools() is None  # home@1 active: no pools
    variants.activate(variants.CONTROL)
    _stranger_posts(1, age=w.NOW - (timezone.now() - timedelta(hours=1)))
    first = tasks.rebuild_pools()
    assert first and first["eligible"] >= 0
    assert tasks.rebuild_pools() == {"due": False}  # pools.rebuild_s not passed
    assert tasks.rebuild_pools(force=True)["sets"]
