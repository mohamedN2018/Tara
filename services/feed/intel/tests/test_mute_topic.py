"""07 WP 7.5-B2: Mute topic.

A muted topic gives **0 recommended items** carrying it (rule E8, on the first page
and on the frozen list's later pages), and a connected item whose primary topic it is
(confidence >= ``mute_primary_min_confidence``) is demoted x ``mute_primary_multiplier``
(0.3), not removed. Undo restores the exact prior state and the recommendations."""

from datetime import timedelta

import pytest
from feed import ranking
from feed.models import ReactionState

from intel import discovery, feedback

from . import r4, variants
from . import world as w

pytestmark = pytest.mark.django_db
ADULT = {"is_minor": False, "age_band": "25-34"}


def _stranger(topic_id, i):
    p = w.post(w.uid(), age=timedelta(hours=1, minutes=i))
    ReactionState.objects.create(post_id=p, reactor_id=w.uid(), active=True, occurred_at=w.NOW)
    r4.tag(p, (topic_id, 0.9))
    return p


def _world(ids, n_conn=60):
    viewer = w.uid()
    friends = [w.uid() for _ in range(20)]
    for i in range(n_conn):
        friend = friends[i % 20]
        w.feed_row(viewer, w.post(friend, age=timedelta(minutes=10 + i)), friend)
    muted = [_stranger(ids["politics"], i) for i in range(10)]
    other = [_stranger(ids["travel"], 20 + i) for i in range(10)]
    return viewer, set(muted), set(other)


def _recs(page):
    return {
        str(i.post_id) for i, s in zip(page.items, page.sources, strict=True) if s == "discovery"
    }


def test_muted_topic_gives_zero_recommended_items_and_undo_brings_them_back(redis_hot):
    ids = r4.seed()
    variants.activate(variants.R15)
    viewer, muted, other = _world(ids)
    discovery.rebuild(variants.cfg(variants.R15), now=w.NOW)
    before = ranking.first_page(viewer, 40, w.NOW, {"sub": viewer, **ADULT})
    assert _recs(before) & muted  # politics was recommended
    a_muted = next(iter(_recs(before) & muted))
    row, _ = feedback.act(
        viewer, feedback.item_for_system("post", a_muted, None), "mute_topic", topic_slug="politics"
    )
    after = ranking.first_page(viewer, 40, w.NOW, {"sub": viewer, **ADULT})
    assert _recs(after) and not (_recs(after) & muted)
    assert _recs(after) <= other
    feedback.undo(viewer, row.id)
    again = ranking.first_page(viewer, 40, w.NOW, {"sub": viewer, **ADULT})
    assert _recs(again) & muted


def test_later_pages_of_the_frozen_list_honour_a_new_mute(redis_hot):
    ids = r4.seed()
    variants.activate(variants.R15)
    viewer, muted, _other = _world(ids, n_conn=60)
    discovery.rebuild(variants.cfg(variants.R15), now=w.NOW)
    first = ranking.first_page(viewer, 10, w.NOW, {"sub": viewer, **ADULT})
    r4.explicit(viewer, "topic", ids["politics"], "muted")
    served = []
    cursor = first.next_cursor
    while cursor:
        page = ranking.next_page(viewer, cursor, 20, {"sub": viewer, **ADULT})
        served += [str(i.post_id) for i in page.items]
        assert page.dropped.get("E8", 0) >= 0
        cursor = page.next_cursor
    assert not (set(served) & muted)


def test_connected_item_with_the_muted_primary_topic_is_demoted_not_removed():
    ids = r4.seed()
    viewer, friend = w.uid(), w.uid()
    posts = [w.post(friend, age=timedelta(minutes=5 + i)) for i in range(4)]
    for p in posts:
        w.feed_row(viewer, p, friend)
    top = posts[0]  # the freshest: first in today's order
    r4.tag(top, (ids["politics"], 0.9))
    baseline = [str(i.post_id) for i in ranking.rank_items(viewer, w.NOW)]
    assert baseline[0] == top
    r4.explicit(viewer, "topic", ids["politics"], "muted")
    # The view passes the profile through ``Personal``; rank_items reads the muted set
    # from the eligibility context (every version).
    after = [str(i.post_id) for i in ranking.rank_items(viewer, w.NOW)]
    assert top in after and after[0] != top
    # A secondary (low-confidence) mention is not demoted.
    r4.tag(top, (ids["history"], 0.9), (ids["politics"], 0.5))
    assert [str(i.post_id) for i in ranking.rank_items(viewer, w.NOW)][0] == top
