"""WP 4b.6 / 02 section 16: the popular pool counts only non-suspect reactions. Reactions
flagged ``suspect`` at ingest, from accounts younger than
``integrity.suspect_account_age_hours`` when they reacted, past
``integrity.suspect_burst_per_min`` in one minute, or from synthetic actors (unless
``INTEL_SYNTHETIC_IN_RANKING``) never make a post popular."""

from datetime import timedelta

import pytest
from feed.models import AuthorRef, ReactionState

from intel import discovery, hot, origin
from intel.models import SyntheticAccount

from . import variants
from . import world as w

pytestmark = pytest.mark.django_db


def _popular(redis_hot):
    key = redis_hot.make_key(hot.pool_key("home", "en", "popular"))
    return {m.decode(): s for m, s in hot.raw_client().zrevrange(key, 0, -1, withscores=True)}


def _react(post_id, reactor=None, *, at=None, suspect=False):
    reactor = reactor or w.uid()
    ReactionState.objects.create(
        post_id=post_id,
        reactor_id=reactor,
        active=True,
        occurred_at=at or w.NOW - timedelta(hours=1),
        suspect=suspect,
    )
    return reactor


def test_flagged_reactions_do_not_count(redis_hot):
    p = w.post(w.uid())
    for _ in range(4):
        _react(p, suspect=True)
    discovery.rebuild(variants.cfg(), now=w.NOW)
    assert p not in _popular(redis_hot)


def test_reactions_from_brand_new_accounts_do_not_count(redis_hot):
    cfg = variants.cfg()
    assert cfg.get("integrity.suspect_account_age_hours") == 24
    farmed, organic = w.post(w.uid()), w.post(w.uid())
    when = w.NOW - timedelta(hours=1)
    for _ in range(5):
        reactor = _react(farmed, at=when)
        AuthorRef.objects.create(
            account_id=reactor, occurred_at=when, registered_at=when - timedelta(hours=2)
        )
    reactor = _react(organic, at=when)
    AuthorRef.objects.create(
        account_id=reactor, occurred_at=when, registered_at=when - timedelta(days=30)
    )
    discovery.rebuild(cfg, now=w.NOW)
    pool = _popular(redis_hot)
    assert farmed not in pool and organic in pool


def test_reactions_past_the_burst_limit_do_not_count(redis_hot):
    cfg = variants.cfg(integrity={"suspect_burst_per_min": 3})
    reactor = w.uid()
    start = w.NOW - timedelta(hours=1)
    posts = [w.post(w.uid()) for _ in range(5)]
    for i, p in enumerate(posts):  # five reactions within ten seconds
        _react(p, reactor, at=start + timedelta(seconds=2 * i))
    discovery.rebuild(cfg, now=w.NOW)
    pool = _popular(redis_hot)
    # The first three are within the limit (the reactor's 1st to 3rd in the minute).
    assert set(posts[:3]) <= set(pool)
    assert not set(posts[3:]) & set(pool)


def test_synthetic_reactors_count_only_where_synthetic_data_may_rank(redis_hot, settings):
    settings.INTEL_SYNTHETIC_IN_RANKING = False
    p = w.post(w.uid())
    bot = w.uid()
    SyntheticAccount.objects.create(account_id=bot, label="seed-reactor")
    origin.clear_cache()
    _react(p, bot)
    discovery.rebuild(variants.cfg(), now=w.NOW)
    assert p not in _popular(redis_hot)
    settings.INTEL_SYNTHETIC_IN_RANKING = True
    discovery.rebuild(variants.cfg(), now=w.NOW)
    assert p in _popular(redis_hot)


def test_score_is_smoothed_engagement_per_hour(redis_hot):
    cfg = variants.cfg()
    pop = cfg.section("pools")["popular"]
    p = w.post(w.uid(), age=timedelta(hours=4))
    for _ in range(3):
        _react(p)
    discovery.rebuild(cfg, now=w.NOW)
    expected = (3 * cfg.get("engagement.reaction") + pop["prior_engagement"]) / (
        4 + pop["prior_hours"]
    )
    assert _popular(redis_hot)[p] == pytest.approx(expected)
