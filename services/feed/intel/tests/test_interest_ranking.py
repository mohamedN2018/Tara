"""04 WP 6.5: ``interest_rel`` in ranking, under the home@3 drafts only.

Backdated synthetic profile: items in the viewer's top topic move up, items in a
disliked topic move down; home@2c (the same params without ``interest_rank``) and
home@1 are unchanged by the same profile (interest_rel stays 0 there)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from intel import config, eligibility, interests
from intel.ranking import home
from intel.ranking.personal import Personal

from . import r4, variants
from . import world as w

pytestmark = pytest.mark.django_db


def _world(ids):
    viewer = w.uid()
    posts = {}
    for i, topic in enumerate(["cooking", "technology", "politics", "travel"] * 3):
        friend = w.uid()
        p = w.post(friend, age=timedelta(minutes=5 + 7 * i))
        w.feed_row(viewer, p, friend)
        r4.tag(p, (ids[topic], 0.9))
        posts[p] = topic
    return viewer, posts


def _order(viewer, cfg, profile):
    personal = Personal(profile=profile)
    ranked = home.rank(eligibility.Viewer(id=viewer), w.NOW, cfg, personal=personal)
    return [s.feats.post_id for s in ranked.items]


def _mean_rank(order, posts, topic):
    positions = [i for i, p in enumerate(order) if posts[p] == topic]
    return sum(positions) / len(positions)


def test_top_topic_moves_up_and_disliked_topic_moves_down():
    ids = r4.seed()
    viewer, posts = _world(ids)
    then = timezone.now() - timedelta(days=2)
    r4.inferred(viewer, "topic", ids["cooking"], 6.0, at=then)
    r4.explicit(viewer, "topic", ids["politics"], "dislike")
    block = config.for_surface("home").section("interests")
    profile = interests.build_profile(viewer, timezone.now(), block)
    assert profile.topic[ids["cooking"]] > 0 and profile.topic[ids["politics"]] < 0
    h3 = variants.cfg(variants.H3)
    base = _order(viewer, h3, interests.Profile())
    ranked = _order(viewer, h3, profile)
    assert _mean_rank(ranked, posts, "cooking") < _mean_rank(base, posts, "cooking")
    assert _mean_rank(ranked, posts, "politics") > _mean_rank(base, posts, "politics")


def test_versions_without_interest_rank_ignore_the_profile():
    ids = r4.seed()
    viewer, posts = _world(ids)
    r4.inferred(viewer, "topic", ids["cooking"], 6.0)
    profile = interests.build_profile(
        viewer, timezone.now(), config.for_surface("home").section("interests")
    )
    for cfg in (variants.cfg("home@2c"), config.for_surface("home")):
        assert _order(viewer, cfg, profile) == _order(viewer, cfg, None)


def test_the_profile_cache_round_trips_and_is_dropped_on_an_explicit_change(
    redis_hot, django_capture_on_commit_callbacks
):
    from intel import hot

    ids = r4.seed()
    viewer = w.uid()
    r4.inferred(viewer, "topic", ids["books"], 3.0)
    block = config.for_surface("home").section("interests")
    built = interests.cached_profile(viewer, timezone.now(), block)
    raw = hot.raw_get(hot.profile_key(viewer))
    assert interests.Profile.from_bytes(raw).topic == pytest.approx(built.topic)
    with django_capture_on_commit_callbacks(execute=True):
        interests.set_explicit(viewer, "topic", str(ids["music"]), "like")
    assert hot.raw_get(hot.profile_key(viewer)) is None
