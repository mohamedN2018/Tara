"""06 section 16, scenario A (new user; 07 WP 6.6-B2): with no connections and no
profile, page 1 has 20 items, at least 60% recommended, every one eligible, from the
basic popular / fresh pools of WP 4b.6 (no 9.1 pools), under home@2b-r15 and
home@3-r15."""

from datetime import timedelta

import pytest
from feed import ranking
from feed.models import ReactionState

from intel import discovery, eligibility
from intel.retrieval.sources import Candidate

from . import variants
from . import world as w

pytestmark = pytest.mark.django_db
ADULT = {"is_minor": False, "age_band": "25-34"}


@pytest.mark.parametrize("label", [variants.R15, variants.H3_R15])
def test_new_user_page_1(redis_hot, label):
    variants.activate(label)
    for i in range(40):
        p = w.post(w.uid(), age=timedelta(hours=1, minutes=i))
        ReactionState.objects.create(post_id=p, reactor_id=w.uid(), active=True, occurred_at=w.NOW)
    # Ineligible public posts the pools must not serve.
    blocked_author = w.uid()
    w.post(blocked_author)
    w.post(w.uid(), author_age="minor")
    viewer = w.uid()
    w.block(viewer, blocked_author)
    discovery.rebuild(variants.cfg(label), now=w.NOW)
    page = ranking.first_page(viewer, 20, w.NOW, {"sub": viewer, **ADULT})
    assert len(page.items) == 20
    recommended = [s for s in page.sources if s == discovery.SOURCE]
    assert len(recommended) / 20 >= 0.6
    # Every item passes the full eligibility filter with the viewer's claims.
    cfg = variants.cfg(label)
    cands = [
        Candidate(str(i.post_id), str(i.author_id), s, i.reason, i.post_created_at)
        for i, s in zip(page.items, page.sources, strict=True)
    ]
    ctx = eligibility.load_context(
        eligibility.Viewer.from_claims({"sub": viewer, **ADULT}), cands, cfg
    )
    assert [eligibility.evaluate(c, ctx) for c in cands] == [None] * 20
    assert blocked_author not in {str(i.author_id) for i in page.items}
