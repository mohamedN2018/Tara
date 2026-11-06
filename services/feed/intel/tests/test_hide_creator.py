"""07 WP 7.5-B2: "Don't recommend this creator".

A hidden creator gives **0 recommended items** with them (rule E8); a followed or
friend creator's connected posts still show; graph hears ``intel.creator.hidden``
(true, then false on undo) to drop them from people suggestions."""

from datetime import timedelta

import pytest
from feed.models import OutboxEvent, ReactionState

from intel import discovery, eligibility, feedback
from intel.ranking import home

from . import variants
from . import world as w

pytestmark = pytest.mark.django_db
ADULT = {"is_minor": False, "age_band": "25-34"}


def test_hidden_creator_leaves_recommendations_but_not_connections(redis_hot):
    from . import r4

    r4.seed()
    variants.activate(variants.R15)
    viewer = w.uid()
    friends = [w.uid() for _ in range(20)]
    for i in range(60):
        f = friends[i % 20]
        w.feed_row(viewer, w.post(f, age=timedelta(minutes=10 + i)), f)
    creator = w.uid()
    theirs = set()
    for i in range(8):
        p = w.post(creator, age=timedelta(hours=1, minutes=i))
        ReactionState.objects.create(post_id=p, reactor_id=w.uid(), active=True, occurred_at=w.NOW)
        theirs.add(p)
    for i in range(10):
        p = w.post(w.uid(), age=timedelta(hours=2, minutes=i))
        ReactionState.objects.create(post_id=p, reactor_id=w.uid(), active=True, occurred_at=w.NOW)
    # The viewer also follows the creator: one connected post of theirs.
    followed = w.post(creator, age=timedelta(minutes=1))
    w.feed_row(viewer, followed, creator, reason="follow")
    discovery.rebuild(variants.cfg(variants.R15), now=w.NOW)

    def page():
        # The whole frozen list of the first page (every page of the session).
        ranked = home.rank(
            eligibility.Viewer.from_claims({"sub": viewer, **ADULT}),
            w.NOW,
            variants.cfg(variants.R15),
        )
        return {(s.feats.post_id, s.feats.source) for s in ranked.items}

    before = page()
    assert any(pid in theirs and s == "discovery" for pid, s in before)
    assert (followed, "connections") in before
    row, _ = feedback.act(
        viewer, feedback.Item("profile", creator, creator, ()), "hide_creator", surface="profile"
    )
    after = page()
    assert not any(pid in theirs for pid, s in after if s == "discovery")
    assert (followed, "connections") in after  # still on the viewer's feed
    events = OutboxEvent.objects.filter(event_type="intel.creator.hidden").order_by("created_at")
    assert [e.payload["payload"]["hidden"] for e in events] == [True]
    feedback.undo(viewer, row.id)
    events = OutboxEvent.objects.filter(event_type="intel.creator.hidden").order_by("created_at")
    assert [e.payload["payload"]["hidden"] for e in events] == [True, False]
    assert any(pid in theirs and s == "discovery" for pid, s in page())
