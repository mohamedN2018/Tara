"""R3 WP A4 (07 WP 4b.5, 06 sections 5.3 and 5.4): the exposure multiplier and rotation.

Frozen clock. The revisit numbers are 07's (computed from 06 section 5.3): a displayed
item is back to ``m >= 0.9`` at +26 h after one exposure and +40 h after two (37.6 h);
a consumed item is still ``m < 0.9`` at +11 days (0.874) and back at +12.5 d after one
exposure (12.35 d) and +16.5 d after two (16.2 d). 09 R3 says "a consumed one at +11
days": that contradicts 06/07's arithmetic (R3 track A report, deviation 1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from feed.models import AuthorRef, CommentState

from intel import config, exposure
from intel.config import schema
from intel.eligibility import Viewer
from intel.models import RankingConfig
from intel.ranking import exposure_rank, home
from intel.tests import world as w

pytestmark = pytest.mark.django_db

NOW = w.NOW
BLOCK = config.from_params("home", {}).section("exposure")
E = exposure_rank.Exposure


def m(state, hours, exposures=1, in_visit=False):
    minute = int((NOW - timedelta(hours=hours)).timestamp() // 60)
    return exposure_rank.multiplier(E(state, minute, exposures, in_visit), NOW, BLOCK)


def test_retrieved_only_keeps_full_score():
    assert exposure_rank.multiplier(None, NOW, BLOCK) == 1.0


def test_displayed_recovers_in_26h_after_one_exposure_40h_after_two():
    d = exposure.STATE_DISPLAYED
    assert m(d, 25.9) < 0.9 <= m(d, 26.1)  # 06: 26.0 h (26.03 exactly)
    assert m(d, 37) ** 1 < 0.95  # two exposures need m >= 0.949 (06 table: 37.6 h)
    assert m(d, 40, exposures=2) >= 0.9
    assert m(d, 36, exposures=2) < 0.9


def test_consumed_recovers_in_12_5_days_after_one_16_5_after_two():
    c = exposure.STATE_CONSUMED
    assert m(c, 11 * 24) == pytest.approx(0.874, abs=0.001)
    assert m(c, 11 * 24) < 0.9
    assert m(c, 12.5 * 24) >= 0.9
    assert m(c, 12.5 * 24, exposures=2) < 0.9
    assert m(c, 16.5 * 24, exposures=2) >= 0.9


def test_in_visit_display_uses_the_stronger_m0():
    d = exposure.STATE_DISPLAYED
    assert m(d, 0.01, in_visit=True) < m(d, 0.01)
    assert m(d, 0.0, in_visit=True) == pytest.approx(BLOCK["in_visit_m0"]["displayed"])


def test_exposures_are_capped_by_max_exposures():
    v = exposure.STATE_VIEWED
    assert m(v, 1, exposures=5) == pytest.approx(m(v, 1, exposures=2))


# ---- the ranking -----------------------------------------------------------------


def v2c() -> config.SurfaceConfig:
    row = RankingConfig.objects.get(surface="home", note="home@2c")
    return config.for_version("home", row.version)


def test_only_versions_with_rotation_apply_it():
    assert exposure_rank.applies(v2c())
    assert not exposure_rank.applies(config.from_params("home", {}))  # home@1 + package keys
    for label in ("home@2b", "home@2b-r15", "home@2b-r30"):
        row = RankingConfig.objects.get(surface="home", note=label)
        assert not schema.exposure_ranking(config.for_version("home", row.version).params)
    # ... though every version resolves the ingest and visit keys.
    old = config.from_params("home", {})
    assert old.get("exposure.ledger.cap") == 200 and old.get("session.ongoing_idle_s") == 1800


def _world(n=12):
    viewer = w.uid()
    posts = []
    for i in range(n):
        friend = w.uid()
        p = w.post(friend, age=timedelta(hours=2, minutes=i))
        w.feed_row(viewer, p, friend)
        posts.append(p)
    return viewer, posts


def _fold(records, visit_ord=5):
    raw = b"".join(
        exposure.encode_record(
            uuid.UUID(p).bytes[:8], int((NOW - ago).timestamp() // 60), state, vo
        )
        for p, state, ago, vo in records
    )
    return exposure.fold(raw, visit_ord)


def _rank(viewer, ctx, cfg=None):
    return home.rank(Viewer(viewer, is_minor=False, age_band="25-34"), NOW, cfg or v2c(), ctx)


def test_displayed_items_sink_and_retrieved_ones_keep_their_place():
    viewer, posts = _world()
    base = [s.feats.post_id for s in _rank(viewer, exposure_rank.Context(now=NOW)).items]
    seen = base[:3]
    folds = _fold([(p, exposure.STATE_VIEWED, timedelta(minutes=45), 4) for p in seen])
    ctx = exposure_rank.Context(now=NOW, folds=folds, previous_head=frozenset(base[:10]))
    ranking = _rank(viewer, ctx)
    order = [s.feats.post_id for s in ranking.items]
    assert all(order.index(p) >= 3 for p in seen)
    # Retrieved in the previous head but never displayed: full score (carry-over).
    assert ranking.exposure.carry_over == 7
    assert all(ranking.exposure.m[p] == 1.0 for p in base[3:10])
    assert [p for p in order if p not in seen][:7] == base[3:10]


def test_without_signals_a_refresh_returns_the_same_head():
    viewer, posts = _world(20)
    a = [s.feats.post_id for s in _rank(viewer, exposure_rank.Context(now=NOW)).items][:10]
    ctx = exposure_rank.Context(now=NOW + timedelta(seconds=60), previous_head=frozenset(a))
    b = [s.feats.post_id for s in _rank(viewer, ctx).items][:10]
    assert a == b


def test_durable_engagement_counts_after_the_hot_window(django_db_blocker):
    from django.db import connection

    viewer, posts = _world()
    target = posts[0]
    shown = NOW - timedelta(days=3)
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO intel_user_item_engagement (account_id, item_id, item_type, first_at,"
            " last_at, data_origin, state, last_displayed_at, visits)"
            " VALUES (%s, %s, 'post', now(), now(), 'test', 3, %s, 1)",
            [viewer, target, shown],
        )
    ranking = _rank(viewer, exposure_rank.Context(now=NOW))
    expected = m(exposure.STATE_CONSUMED, 72)
    assert ranking.exposure.m[target] == pytest.approx(expected)


def test_new_comments_from_distinct_real_accounts_lift_a_consumed_item():
    viewer, posts = _world()
    target = posts[0]
    author = str(home.rank(Viewer(viewer), NOW, v2c()).content[target]["author_id"])
    folds = _fold([(target, exposure.STATE_CONSUMED, timedelta(hours=2), 4)])
    ctx = exposure_rank.Context(now=NOW, folds=folds)
    assert _rank(viewer, ctx).exposure.m[target] < 0.8
    needed = v2c().get("revisit.new_comments")

    def comment(by, minutes_ago):
        CommentState.objects.create(
            comment_id=uuid.uuid4(),
            post_id=target,
            author_id=by,
            post_author_id=author,
            active=True,
            occurred_at=NOW - timedelta(minutes=minutes_ago),
        )

    for _ in range(needed - 1):
        comment(w.uid(), 30)
    comment(author, 20)  # the author's own reply does not count
    comment(viewer, 10)  # nor does the viewer's
    young = w.uid()
    AuthorRef.objects.create(account_id=young, occurred_at=NOW, registered_at=NOW)
    comment(young, 5)  # a suspect (brand-new) account does not count
    assert _rank(viewer, ctx).exposure.m[target] < 0.8
    comment(w.uid(), 3)
    ranking = _rank(viewer, ctx)
    assert ranking.exposure.m[target] == pytest.approx(v2c().get("revisit.min_m"))
    assert ranking.exposure.new_activity == 1


def test_the_floor_keeps_low_relevance_out_of_the_first_slots():
    cfg = v2c()
    s = [_fake(i, pre, post) for i, (pre, post) in enumerate([(10, 1), (9, 9), (1, 1), (8, 8)])]
    stats = exposure_rank.Stats(pre={x.feats.post_id: p for x, p in s_pre(s)})
    for x, (_, post) in zip(s, [(10, 1), (9, 9), (1, 1), (8, 8)], strict=True):
        x.value = post
    out = exposure_rank.floor(s, stats, cfg, page_size=20)
    # Threshold 0.25 x p95(pre) ~ 2.4: item 2 (pre 1) is low-quality filler and goes
    # last; item 0 (pre 10, seen: score' 1) is a "best seen" filler, after 1 and 3.
    assert [x.feats.post_id for x in out] == ["p1", "p3", "p0", "p2"]


def _fake(i, pre, post):
    from intel.ranking.features import CandidateFeatures
    from intel.ranking.scorer import Scored

    f = CandidateFeatures(
        post_id=f"p{i}",
        author_id="a",
        source="connections",
        reason="friend",
        tie_id=f"p{i}",
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
        age_h=1,
        type="text",
        lang="en",
        group_id=None,
        is_reshare=False,
        duplicate=False,
        bait_score=None,
        pending_reports=0,
        moderation_open=False,
        duration_ms=None,
        media_quality=None,
        has_stats=False,
        reactions=0,
        comments=0,
        shares=0,
        flags=0,
        stored_score=None,
        reach=0,
        hides=0,
        commenters=0,
        favorite=False,
        affinity=0,
        author_dislikes=0,
        shared_groups=0,
        conversation=0.0,
    )
    return Scored(f, None, pre)


def s_pre(items):
    return [(x, x.value) for x in items]


@pytest.fixture
def _no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


def test_serving_never_writes_the_ledger(client_for, redis_hot, _no_ads):
    """``retrieved`` gets no state: first pages, refreshes and later pages never write
    ``feed:exp`` (only feed-signals ingest does)."""
    from intel import hot
    from intel.config import store

    store.activate("home", RankingConfig.objects.get(surface="home", note="home@2c").version)
    viewer, _ = _world(30)
    client = client_for(viewer)
    body = client.get("/api/v1/feed/", {"mode": "for_you", "entry": "load"}).json()
    client.get("/api/v1/feed/", {"mode": "for_you", "cursor": body["page"]["next_cursor"]})
    client.get("/api/v1/feed/", {"mode": "for_you", "entry": "pull"})
    client.get("/api/v1/feed/", {"mode": "for_you", "peek": "1"})
    key = hot.hot().make_key(exposure.ledger_key(viewer))
    assert not hot.raw_client().exists(key)
