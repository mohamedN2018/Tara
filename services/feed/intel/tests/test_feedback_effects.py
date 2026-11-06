"""WP 7.2: the effects of each feedback action (``feedback_effects`` in the config).

``not_interested`` now also down-weights the author (-2 on the creator row): an
owner-visible change that **replaces** the phase-2 test
``feed/tests/test_hide_rank.py::test_not_interested_does_not_downweight_the_author``
(listed in results/r4-track-a.md). A plain hide keeps today's behaviour exactly (no
author penalty from a ``not_interested`` hide reason). ``reel.hidden`` maps to
``not_interested`` on the reel."""

import pytest
from feed import ranking

from intel import feedback
from intel.models import FeedbackAction, UserInterest

from . import r4
from . import world as w
from .helpers import deliver, event

pytestmark = pytest.mark.django_db


def _v(account, dim, key):
    row = UserInterest.objects.filter(
        account_id=account, dim=dim, key=str(key), source="inferred"
    ).first()
    return None if row is None else round(row.long_v, 4)


@pytest.mark.parametrize(
    ("action", "topic_delta", "author_delta"),
    [
        ("interested", 3.0, None),
        ("more_like_this", 3.0, None),
        ("less_like_this", -2.0, None),
        ("not_interested", -4.0, -2.0),
    ],
)
def test_each_action_moves_topics_and_author(action, topic_delta, author_delta):
    ids = r4.seed()
    viewer, author = w.uid(), w.uid()
    p = w.post(author)
    r4.tag(p, (ids["gaming"], 1.0), (ids["design"], 0.5))
    feedback.act(viewer, feedback.item_for_system("post", p, author), action)
    assert _v(viewer, "topic", ids["gaming"]) == pytest.approx(topic_delta, abs=1e-3)
    assert _v(viewer, "topic", ids["design"]) == pytest.approx(topic_delta * 0.5, abs=1e-3)
    assert _v(viewer, "creator", author) == (
        None if author_delta is None else pytest.approx(author_delta, abs=1e-3)
    )


def test_not_interested_feedback_downweights_the_author_explicitly(client_for):
    """Replaces the phase-2 ``test_not_interested_does_not_downweight_the_author``: the
    explicit Not interested action now writes -2 on the creator (the hide path itself
    still adds no author penalty, as before)."""
    r4.seed()
    viewer, author = w.uid(), w.uid()
    hidden = w.post(author)
    w.feed_row(viewer, hidden, author)
    client_for(viewer).post("/api/v1/feed/hide/", {"post_id": hidden, "reason": "not_interested"})
    assert ranking.author_penalties(viewer, [author]) == {}  # today's hide, unchanged
    other = w.post(author)
    w.feed_row(viewer, other, author)
    resp = client_for(viewer).post(
        "/api/v1/feed/feedback/",
        {"item_type": "post", "item_id": other, "action": "not_interested"},
        format="json",
    )
    assert resp.status_code == 201
    assert _v(viewer, "creator", author) == pytest.approx(-2.0, abs=1e-3)


def test_reel_hidden_maps_to_not_interested():
    ids = r4.seed()
    viewer, author = w.uid(), w.uid()
    reel = w.post(author, type="reel")
    r4.tag(reel, (ids["music"], 0.8))
    env = event("reel.hidden", {"post_id": reel, "viewer_id": viewer, "author_id": author})
    deliver(env, times=2, only_intel=True)
    row = FeedbackAction.objects.get(account_id=viewer, item_id=reel)
    assert row.action == "not_interested" and row.surface == "reels" and row.item_type == "reel"
    assert _v(viewer, "topic", ids["music"]) == pytest.approx(-3.2, abs=1e-3)
    assert _v(viewer, "creator", author) == pytest.approx(-2.0, abs=1e-3)
