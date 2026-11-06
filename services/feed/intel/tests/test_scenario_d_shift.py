"""06 section 16, scenario D (interest shift), under home@3: a viewer whose long-term
interest is technology consumes 4 cooking items in the session; on the next page 1
cooking rises by at least 2 items and technology keeps at least 30%."""

from datetime import timedelta

import pytest
from django.utils import timezone

from intel import config, eligibility, interests, session_ctx
from intel.ranking import home
from intel.ranking.personal import Personal

from . import r4, variants
from . import world as w

pytestmark = pytest.mark.django_db


def _page_topics(viewer, cfg, personal, posts):
    ranked = home.rank(eligibility.Viewer(id=viewer), w.NOW, cfg, personal=personal)
    return [posts[s.feats.post_id] for s in ranked.items[:20]]


def test_four_cooking_consumptions_shift_page_1_and_technology_stays():
    ids = r4.seed()
    viewer = w.uid()
    posts = {}
    for i in range(24):
        for topic in ("technology", "cooking"):
            friend = w.uid()
            # Interleaved over two days, so freshness spreads the scores like a real feed.
            p = w.post(friend, age=timedelta(hours=2 * i + (1 if topic == "cooking" else 0)))
            w.feed_row(viewer, p, friend)
            r4.tag(p, (ids[topic], 0.9))
            posts[p] = topic
    r4.inferred(viewer, "topic", ids["technology"], 8.0, at=timezone.now() - timedelta(days=5))
    cfg = variants.cfg(variants.H3)
    profile = interests.build_profile(viewer, timezone.now(), cfg.section("interests"))
    before = _page_topics(viewer, cfg, Personal(profile=profile, si=None), posts)
    # Four cooking consumptions in the last minutes (the vector ingest would write).
    block = cfg.section("session_interest")
    minute = session_ctx.si_minute(timezone.now())
    si_raw = {
        f"t:{ids['cooking']}".encode(): f"4.0:{minute - 3}".encode(),
        b"f:text": f"4.0:{minute - 3}".encode(),
        b"n": b"4",
    }
    si = session_ctx.si_decode(si_raw, timezone.now(), block)
    after = _page_topics(viewer, cfg, Personal(profile=profile, si=si), posts)
    assert after.count("cooking") >= before.count("cooking") + 2, (before, after)
    assert after.count("technology") >= 6  # >= 30% of 20
    # Without the session term (home@2c) the same vector changes nothing.
    c2 = variants.cfg("home@2c")
    assert _page_topics(viewer, c2, Personal(si=si), posts) == _page_topics(
        viewer, c2, Personal(), posts
    )
    _ = config
