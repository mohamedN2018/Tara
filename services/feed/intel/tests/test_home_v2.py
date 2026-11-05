"""WP 4.3: ``home@2`` (groups, predictions, quality, integrity, diversity). Each term
moves its item in the expected direction, all else equal."""

from datetime import timedelta

import pytest
from django.db import connection
from feed.models import CommentState, PostHide, PostStats

from intel import config
from intel.eligibility import Viewer
from intel.models import ContentRef, MediaRef
from intel.ranking import home
from intel.tests import world as w

pytestmark = pytest.mark.django_db


def v2(**overrides):
    return config.from_params("home", {**config.store.defaults("home", 2), **overrides})


def _rank(viewer, cfg=None):
    return [s.feats.post_id for s in home.rank(Viewer(viewer), w.NOW, cfg or v2()).items]


def _pair(viewer, *, age=timedelta(hours=1), type="text"):  # noqa: A002
    """Two connection posts by two friends, identical in every input."""
    a, b = w.uid(), w.uid()
    pa = w.post(a, age=age, type=type)
    pb = w.post(b, age=age, type=type)
    w.feed_row(viewer, pa, a, "friend", type=type)
    w.feed_row(viewer, pb, b, "friend", type=type)
    return (pa, a), (pb, b)


def _below(order, low, high):
    return order.index(low) > order.index(high)


def test_v2_brings_joined_group_posts_v1_does_not():
    viewer, author = w.uid(), w.uid()
    g = w.group(owner=w.uid())
    w.member(viewer, g)
    gp = w.post(author, audience="group", group=g)
    assert gp in _rank(viewer)
    assert gp not in _rank(viewer, config.from_params("home", {}))


def test_more_likes_rank_higher_through_the_predictions():
    viewer = w.uid()
    (pa, _), (pb, _) = _pair(viewer)
    PostStats.objects.create(post_id=pb, reactions=30, comments=5)
    assert _below(_rank(viewer), pa, pb)


def test_hides_rank_lower_through_score_negative():
    viewer = w.uid()
    (pa, a), (pb, _) = _pair(viewer)
    for _ in range(5):
        PostHide.objects.create(account_id=w.uid(), post_id=pa, author_id=a, reason="other")
    assert _below(_rank(viewer), pa, pb)


def test_shared_groups_and_conversation_raise_the_author():
    viewer = w.uid()
    (pa, a), (pb, b) = _pair(viewer)
    g = w.group(owner=w.uid())
    w.member(viewer, g)
    w.member(b, g)
    assert _below(_rank(viewer), pa, pb)

    viewer2 = w.uid()
    (pc, _), (pd, d) = _pair(viewer2)
    for i, (who, whose) in enumerate([(viewer2, d), (d, viewer2), (viewer2, d)]):
        CommentState.objects.create(
            comment_id=w.uid(),
            post_id=w.uid(),
            author_id=who,
            post_author_id=whose,
            occurred_at=w.NOW - timedelta(days=i + 1),
        )
    assert _below(_rank(viewer2), pc, pd)


def test_a_reshare_ranks_below_an_original():
    viewer = w.uid()
    (pa, _), (pb, _) = _pair(viewer)
    ContentRef.objects.filter(post_id=pa).update(shared_post_id=w.uid())
    assert _below(_rank(viewer), pa, pb)


def test_media_quality_raises_a_video():
    viewer = w.uid()
    (pa, _), (pb, _) = _pair(viewer, type="video")
    for post_id, rung in ((pa, 360), (pb, 720)):
        media = w.uid()
        MediaRef.objects.create(
            media_id=media,
            duration_ms=30_000,
            top_rung=rung,
            has_poster=True,
            quality=1.0 if rung == 720 else 0.5,
            updated_at=w.NOW,
        )
        ContentRef.objects.filter(post_id=post_id).update(media_ids=[media])
    assert _below(_rank(viewer), pa, pb)


@pytest.mark.parametrize("signal", ["pending", "open_case", "bait", "spam_flags", "duplicate"])
def test_integrity_signals_demote_and_never_remove(signal):
    viewer = w.uid()
    (pa, a), (pb, _) = _pair(viewer)
    if signal == "pending":
        ContentRef.objects.filter(post_id=pa).update(pending_reports=3)
    elif signal == "open_case":
        ContentRef.objects.filter(post_id=pa).update(moderation_open=True)
    elif signal == "bait":
        ContentRef.objects.filter(post_id=pa).update(bait_score=0.75)
    elif signal == "spam_flags":
        PostStats.objects.create(post_id=pa, flags=3)
    else:
        original = w.post(a, age=timedelta(hours=5))
        ContentRef.objects.filter(post_id=pa).update(dup_of=original)
    order = _rank(viewer)
    assert pa in order  # demoted, never removed
    assert _below(order, pa, pb)
    v1 = _rank(viewer, config.from_params("home", {}))
    assert pa in v1


def test_two_pending_reports_are_below_the_threshold():
    viewer = w.uid()
    (pa, _), (pb, _) = _pair(viewer)
    ContentRef.objects.filter(post_id=pa).update(pending_reports=2)
    ranked = home.rank(Viewer(viewer), w.NOW, v2()).items
    by_id = {s.feats.post_id: s for s in ranked}
    assert "pending_reports" not in dict(by_id[pa].contributions)


def test_a_duplicate_whose_original_is_gone_is_not_demoted():
    viewer = w.uid()
    (pa, a), (pb, _) = _pair(viewer)
    original = w.post(a, age=timedelta(hours=5), state="deleted")
    ContentRef.objects.filter(post_id=pa).update(dup_of=original)
    by_id = {s.feats.post_id: s for s in home.rank(Viewer(viewer), w.NOW, v2()).items}
    assert "duplicate" not in dict(by_id[pa].contributions)


def test_freshness_still_matters():
    viewer = w.uid()
    a, b = w.uid(), w.uid()
    old, new = w.post(a, age=timedelta(hours=48)), w.post(b, age=timedelta(minutes=5))
    w.feed_row(viewer, old, a)
    w.feed_row(viewer, new, b)
    assert _rank(viewer) == [new, old]


def test_ineligible_pull_content_never_reaches_scoring():
    viewer, author = w.uid(), w.uid()
    g = w.group(privacy="private", owner=w.uid())
    w.member(viewer, g, state="banned")
    banned_post = w.post(author, audience="group", group=g)
    w.follow(viewer, author, at=w.NOW - timedelta(hours=1))
    only_me = w.post(author, audience="only_me")
    ranking = home.rank(Viewer(viewer), w.NOW, v2())
    ids = [s.feats.post_id for s in ranking.items]
    assert banned_post not in ids and only_me not in ids
    assert sum(ranking.dropped.values()) >= 2


def test_the_v2_query_count_is_bounded():
    from django.test.utils import CaptureQueriesContext

    viewer = w.uid()
    for _ in range(30):
        _pair(viewer)
    with CaptureQueriesContext(connection) as ctx:
        home.rank(Viewer(viewer), w.NOW, v2())
    small = len(ctx.captured_queries)
    for _ in range(100):
        _pair(viewer)
    with CaptureQueriesContext(connection) as ctx:
        home.rank(Viewer(viewer), w.NOW, v2())
    assert len(ctx.captured_queries) == small
