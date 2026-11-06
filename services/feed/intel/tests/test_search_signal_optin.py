"""07 WP 8.7-B2 (owner decision 7): the search signal is opt-in.

- off (the default): a ``search.queried`` changes nothing: no ``feed:si`` entry, no
  row anywhere;
- on: the hashed terms map to topic ids through feed's own aliases and the topics of
  the last 3 searches enter ``feed:si`` (no digest, no text stored); a sensitive topic
  needs the decision-12 opt-in;
- feed tells search with ``intel.search_signal.changed`` (enabled = search_signal
  AND NOT personalization_off).
"""

import pytest
from django.db import connection
from feed.models import OutboxEvent

from intel import hot, preferences
from intel.models import UserInterest
from tara_common.signal_terms import term_keys

from . import r4
from . import world as w
from .helpers import deliver, event

pytestmark = pytest.mark.django_db


def _q(account, query):
    deliver(
        event(
            "search.queried",
            {"account_id": account, "term_keys": term_keys(query), "queried_at": w.NOW.isoformat()},
        ),
        only_intel=True,
    )


def _si(redis_hot, account):
    return hot.raw_client().hgetall(redis_hot.make_key(hot.session_interest_key(account)))


def _enabled_events(account):
    return [
        e.payload["payload"]["enabled"]
        for e in OutboxEvent.objects.filter(event_type="intel.search_signal.changed").order_by(
            "created_at"
        )
        if e.payload["payload"]["account_id"] == account
    ]


def test_off_by_default_nothing_is_stored(redis_hot):
    r4.seed()
    viewer = w.uid()
    _q(viewer, "وصفات طبخ سهلة")
    assert _si(redis_hot, viewer) == {}
    assert not UserInterest.objects.filter(account_id=viewer).exists()
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM intel_signal_event WHERE account_id = %s", [viewer])
        assert cur.fetchone()[0] == 0


def test_on_keeps_the_topics_of_the_last_three_searches(redis_hot):
    ids = r4.seed()
    viewer = w.uid()
    preferences.patch(viewer, {"search_signal": True})
    assert _enabled_events(viewer) == [True]
    for query in ("طبخ", "#برمجة", "سفر", "رياضة"):
        _q(viewer, query)
    raw = _si(redis_hot, viewer)
    stored = raw[b"q"].decode()
    entries = [[int(x) for x in part.split(",")] for part in stored.split(";")]
    assert entries == [[ids["sports"]], [ids["travel"]], [ids["programming"]]]
    # No digest or text in the hash.
    assert all(len(v) < 64 for v in raw.values())
    assert "طبخ" not in str(raw)
    # A sensitive topic needs the opt-in.
    _q(viewer, "سياسة")
    assert str(ids["politics"]) not in _si(redis_hot, viewer)[b"q"].decode().split(";")[0]


def test_personalization_off_disables_the_signal(redis_hot):
    r4.seed()
    viewer = w.uid()
    preferences.patch(viewer, {"search_signal": True})
    preferences.patch(viewer, {"personalization_off": True})
    assert _enabled_events(viewer) == [True, False]
    _q(viewer, "طبخ")
    assert _si(redis_hot, viewer) == {}
