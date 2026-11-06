"""WP 7.1: ``POST/DELETE /api/v1/feed/feedback/``.

One transaction writes the action row, the server signal row and the interest change;
a live repeat returns the same row (200); undo restores the exact prior state; the
item must have been served to the viewer (or be on their own feed) and still be
visible, else one identical 404; an id that is not the caller's is 404."""

import pytest
from django.utils import timezone
from feed.models import OutboxEvent

from intel.models import FeedbackAction, UserInterest
from intel.ranking import serve_tokens

from . import r4
from . import world as w
from .helpers import ADULT_CLAIMS, client_with_claims, signal_rows

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/feedback/"


@pytest.fixture
def ids():
    return r4.seed()


def _connected(viewer, ids, *topics):
    author = w.uid()
    p = w.post(author)
    w.feed_row(viewer, p, author)
    r4.tag(p, *[(ids[t], c) for t, c in topics])
    return p, author


def _state(account):
    return sorted(
        UserInterest.objects.filter(account_id=account).values_list(
            "dim", "key", "source", "polarity", "short_v", "mid_v", "long_v", "events_n"
        )
    )


def test_act_writes_row_signal_and_delta_and_undo_restores_exactly(ids):
    viewer = w.uid()
    p, author = _connected(viewer, ids, ("cooking", 0.9))
    r4.inferred(viewer, "topic", ids["cooking"], 1.25)  # an existing inferred row
    before = _state(viewer)
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    resp = client.post(
        URL, {"item_type": "post", "item_id": p, "action": "less_like_this"}, format="json"
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["action"] == "less_like_this" and data["topics"] == ["cooking"]
    assert data["creator_id"] == author and data["item_id"] == p
    row = UserInterest.objects.get(account_id=viewer, dim="topic", key=str(ids["cooking"]))
    assert row.long_v == pytest.approx(1.25 - 2 * 0.9, rel=1e-3)
    assert [r["event_type"] for r in signal_rows(account_id=viewer)] == ["less_like_this"]
    again = client.post(
        URL, {"item_type": "post", "item_id": p, "action": "less_like_this"}, format="json"
    )
    assert again.status_code == 200 and again.json()["data"]["id"] == data["id"]
    assert client.delete(f"{URL}{data['id']}/").status_code == 204
    assert _state(viewer) == before
    assert FeedbackAction.objects.get(id=data["id"]).undone_at is not None
    assert client.delete(f"{URL}{data['id']}/").status_code == 404  # already undone


def test_unknown_unserved_or_hidden_items_are_404(ids):
    viewer = w.uid()
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    stranger_post = w.post(w.uid())  # public, but never served to the viewer
    for item in (w.uid(), stranger_post):
        resp = client.post(
            URL, {"item_type": "post", "item_id": item, "action": "interested"}, format="json"
        )
        assert resp.status_code == 404
    # Served through a valid serve token: accepted (a recommended item).
    token = serve_tokens.issue(viewer, "post", stranger_post, "home", source="discovery")
    ok = client.post(
        URL,
        {"item_type": "post", "item_id": stranger_post, "action": "interested", "st": token},
        format="json",
    )
    assert ok.status_code == 201
    # A token issued to someone else proves nothing.
    other = serve_tokens.issue(w.uid(), "post", stranger_post, "home", source="discovery")
    resp = client.post(
        URL,
        {"item_type": "post", "item_id": stranger_post, "action": "not_interested", "st": other},
        format="json",
    )
    assert resp.status_code == 404
    # Blocked authors are not visible: 404 even with a token.
    blocked_author = w.uid()
    bp = w.post(blocked_author)
    w.block(viewer, blocked_author)
    token = serve_tokens.issue(viewer, "post", bp, "home", source="discovery")
    resp = client.post(
        URL,
        {"item_type": "post", "item_id": bp, "action": "interested", "st": token},
        format="json",
    )
    assert resp.status_code == 404


def test_someone_elses_action_id_is_404(ids):
    a, b = w.uid(), w.uid()
    p, _ = _connected(a, ids, ("books", 1.0))
    data = (
        client_with_claims(a, **ADULT_CLAIMS)
        .post(URL, {"item_type": "post", "item_id": p, "action": "interested"}, format="json")
        .json()["data"]
    )
    assert client_with_claims(b, **ADULT_CLAIMS).delete(f"{URL}{data['id']}/").status_code == 404


def test_mute_topic_needs_one_of_the_items_topics(ids):
    viewer = w.uid()
    p, _ = _connected(viewer, ids, ("cooking", 0.9))
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    body = {"item_type": "post", "item_id": p, "action": "mute_topic"}
    assert client.post(URL, body, format="json").status_code == 400
    assert client.post(URL, {**body, "topic": "politics"}, format="json").status_code == 400
    assert client.post(URL, {**body, "topic": "cooking"}, format="json").status_code == 201


def test_hide_creator_on_a_profile_and_the_event(ids, settings):
    viewer, creator = w.uid(), w.uid()
    w.author(creator)
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    body = {"item_type": "profile", "item_id": creator, "action": "hide_creator"}
    resp = client.post(URL, body, format="json")
    assert resp.status_code == 201 and resp.json()["data"]["creator_id"] == creator
    events = [
        e.payload["payload"] for e in OutboxEvent.objects.filter(event_type="intel.creator.hidden")
    ]
    assert events[-1]["creator_id"] == creator and events[-1]["hidden"] is True
    assert client.delete(f"{URL}{resp.json()['data']['id']}/").status_code == 204
    events = [
        e.payload["payload"] for e in OutboxEvent.objects.filter(event_type="intel.creator.hidden")
    ]
    assert events[-1]["hidden"] is False
    # Only hide_creator applies to a profile; a blocked or unknown account is 404.
    assert client.post(URL, {**body, "action": "interested"}, format="json").status_code == 400
    assert client.post(URL, {**body, "item_id": w.uid()}, format="json").status_code == 404
    w.block(creator, viewer)
    assert client.post(URL, body, format="json").status_code == 404
    assert client.post(URL, {**body, "item_id": viewer}, format="json").status_code == 404
    _ = timezone.now()
