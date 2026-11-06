"""07 WP 6.8-B2 (06 section 4.5): intent v0 in shadow. Each rule fires on its fixture
(first match wins); with ``overlay_weight`` 0 (every shipped version) the order is
identical to a ranking without intent (golden); a weight above 0 does change the
inputs; the intent is stored in the visit row and in ``feed:si``."""

from datetime import timedelta

import pytest

from intel import config, eligibility, intent, session_ctx
from intel.models import FeedSession
from intel.ranking import home
from intel.ranking.personal import Personal

from . import r4, variants
from . import world as w
from .helpers import ADULT_CLAIMS, client_with_claims

pytestmark = pytest.mark.django_db


class _Visit:
    def __init__(self, kind):
        self.kind = kind


def _cfg():
    return config.for_surface("home")


def test_each_rule_fires_on_its_fixture():
    cfg = _cfg()
    assert intent.classify(_Visit("returning"), None, cfg) == intent.CATCH_UP
    assert intent.finalize(intent.CATCH_UP, None, 5, cfg) == intent.CATCH_UP
    assert intent.finalize(intent.CATCH_UP, None, 0, cfg) == intent.NONE  # nothing new
    video = {"format": {"video": 2.0, "reel": 1.5, "text": 1.0}, "topic": {}, "n": 5}
    assert intent.classify(_Visit("new"), video, cfg) == intent.BROWSE_VIDEO
    focus = {"format": {"text": 4.0}, "topic": {3: 3.0, 4: 0.5}, "n": 4}
    assert intent.classify(_Visit("ongoing"), focus, cfg) == intent.TOPIC_FOCUS
    spread = {"format": {"text": 4.0}, "topic": {3: 1.0, 4: 1.0}, "n": 4}
    assert intent.classify(_Visit("ongoing"), spread, cfg) == intent.NONE
    assert intent.classify(None, None, cfg) == intent.NONE


def test_overlays_at_weight_zero_leave_every_input_unchanged():
    cfg = _cfg()
    block = cfg.section("diversity")
    for name in intent.INTENTS:
        assert intent.overlay(name, cfg, share=0.15, diversity=block) == (0.15, block)
    hot_cfg = config.SurfaceConfig(
        "home",
        cfg.version,
        {**cfg.params, "intent": {**cfg.section("intent"), "overlay_weight": 1.0}},
    )
    share, div = intent.overlay(intent.EXPLORE, hot_cfg, share=0.15, diversity=block)
    assert share == pytest.approx(0.25)
    _, div = intent.overlay(intent.BROWSE_VIDEO, hot_cfg, share=0.15, diversity=block)
    assert div["max_same_format_run"] == 3


def test_golden_intent_overlays_at_zero_give_an_identical_order():
    ids = r4.seed()
    viewer = w.uid()
    for i in range(30):
        friend = w.uid()
        p = w.post(friend, type="video" if i % 3 else "text", age=timedelta(minutes=4 + 6 * i))
        w.feed_row(viewer, p, friend, type="video" if i % 3 else "text")
        r4.tag(p, (ids["gaming"], 0.8))
    cfg = variants.cfg(variants.H3)
    v = eligibility.Viewer(id=viewer)
    without = [s.feats.post_id for s in home.rank(v, w.NOW, cfg, personal=Personal()).items]
    for name in intent.INTENTS:
        with_intent = home.rank(v, w.NOW, cfg, personal=Personal(intent=name)).items
        assert [s.feats.post_id for s in with_intent] == without


def test_the_intent_is_stored_on_the_visit_row(redis_hot, monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    viewer = w.uid()
    friend = w.uid()
    w.feed_row(viewer, w.post(friend), friend)
    client_with_claims(viewer, **ADULT_CLAIMS).get("/api/v1/feed/", {"mode": "for_you"})
    row = FeedSession.objects.get(account_id=viewer)
    assert row.intent == intent.NONE
    _ = session_ctx
