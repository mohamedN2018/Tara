"""R3 WP 4b.13: the engagement aggregator v0 (``intel.signals.aggregate``).

Idempotence (a window run twice, overlapping windows, a lost watermark), the states
and natural-key dedupe, visits, the durable consumed state after the hot TTL, and what
it skips: personalization_off, synthetic and test actors, events before reset_at."""

import json
import uuid
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from intel import exposure
from intel.models import SyntheticAccount, UserPreference
from intel.signals import aggregate
from intel.tasks import aggregate_engagement

from .helpers import acct, batch, ev

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/signals/"


def _send(client, *events, session=None):
    body = batch(*events, session=session or str(uuid.uuid4()))
    resp = client.post(URL, data=json.dumps(body), content_type="application/json")
    assert resp.status_code == 202
    return resp.json()["data"]


def _rows(account=None) -> list[dict]:
    sql = "SELECT * FROM intel_user_item_engagement"
    params = []
    if account:
        sql += " WHERE account_id = %s"
        params = [account]
    with connection.cursor() as cur:
        cur.execute(sql + " ORDER BY account_id, item_id, first_at", params)  # noqa: S608
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _window():
    now = timezone.now()
    return now - timedelta(minutes=5), now + timedelta(seconds=5)


@pytest.fixture(autouse=True)
def _no_watermark():
    cache.delete(aggregate.WATERMARK_KEY)
    aggregate._reset_column = None
    yield
    cache.delete(aggregate.WATERMARK_KEY)


def test_states_counts_and_visits(client_for):
    me = acct()
    c = client_for(me)
    th = exposure.thresholds()
    read, skimmed, liked, watched = (str(uuid.uuid4()) for _ in range(4))
    s1, s2 = str(uuid.uuid4()), str(uuid.uuid4())
    _send(
        c,
        ev("feed_impression", f"post:{read}"),
        ev("feed_dwell", f"post:{read}", dwell_ms=th.consumed_dwell_ms + 10),
        ev("feed_impression", f"post:{skimmed}"),
        ev("feed_dwell", f"post:{skimmed}", dwell_ms=th.skip_dwell_ms - 1),
        ev("feed_impression", f"post:{liked}"),
        ev("video_start", f"video:{watched}", play_index=1),
        ev("video_complete", f"video:{watched}", watch_ms=30_000),
        session=s1,
    )
    # The same tab again (a reload re-reporting), then a second visit (new session).
    _send(c, ev("feed_impression", f"post:{read}"), session=s1)
    _send(c, ev("feed_impression", f"post:{read}"), ev("post_open", f"post:{read}"), session=s2)
    from intel.models import EventType
    from intel.signals import server

    server.record(me, EventType.POST_LIKE, "post", liked)  # a bus-style consumption
    lo, hi = _window()
    out = aggregate.aggregate(lo, hi)
    assert out["pairs"] == 4
    rows = {str(r["item_id"]): r for r in _rows(me)}
    r = rows[read]
    assert (r["impressions"], r["opens"], r["visits"]) == (2, 1, 2)  # 2 sessions
    assert (r["state"], r["consumed_dwell_only"]) == (exposure.STATE_CONSUMED, True)
    assert r["dwell_ms"] == th.consumed_dwell_ms + 10
    assert r["last_displayed_at"] is not None and r["data_origin"] == "real"
    assert rows[skimmed]["state"] == exposure.STATE_SKIPPED
    assert (rows[liked]["state"], rows[liked]["consumed_dwell_only"]) == (
        exposure.STATE_CONSUMED,
        False,
    )
    w = rows[watched]
    assert (w["state"], w["completions"], w["max_watch_ms"]) == (exposure.STATE_CONSUMED, 1, 30_000)
    assert w["consumed_dwell_only"] is False


def test_rerunning_a_window_changes_nothing(client_for):
    me = acct()
    c = client_for(me)
    item = str(uuid.uuid4())
    _send(c, ev("feed_impression", f"post:{item}"), ev("feed_dwell", f"post:{item}", dwell_ms=4000))
    lo, hi = _window()
    aggregate.aggregate(lo, hi)
    first = _rows(me)
    aggregate.aggregate(lo, hi)
    aggregate.aggregate(lo - timedelta(hours=1), hi)  # overlapping, wider
    assert _rows(me) == first and len(first) == 1
    # The beat task with no watermark (first run, flushed cache) is idempotent too.
    aggregate_engagement()
    aggregate_engagement()
    assert _rows(me) == first


def test_dwell_counts_once_per_session_and_item(client_for):
    me = acct()
    c = client_for(me)
    item = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    _send(c, ev("feed_dwell", f"post:{item}", dwell_ms=2000), session=sid)
    _send(c, ev("feed_dwell", f"post:{item}", dwell_ms=2500), session=sid)  # same session
    _send(c, ev("feed_dwell", f"post:{item}", dwell_ms=1000))  # another session
    aggregate.aggregate(*_window())
    assert _rows(me)[0]["dwell_ms"] == 2500 + 1000


def test_consumed_state_survives_the_hot_ttl(client_for):
    """07 WP 4b.13: once the 36 h ledger record expires, the durable row still says
    consumed (the ranker reads it for items older than the hot window)."""
    me = acct()
    item = str(uuid.uuid4())
    th = exposure.thresholds()
    _send(client_for(me), ev("feed_dwell", f"post:{item}", dwell_ms=th.consumed_dwell_ms))
    aggregate.aggregate(*_window())
    later = timezone.now() + timedelta(hours=40)
    # A later run (after the hot TTL) touching nothing keeps the row as it was.
    aggregate.aggregate(later - timedelta(minutes=5), later)
    row = _rows(me)[0]
    assert row["state"] == exposure.STATE_CONSUMED


def test_personalization_off_gets_no_rows(client_for):
    me = acct()
    item = str(uuid.uuid4())
    _send(client_for(me), ev("feed_impression", f"post:{item}"))
    # Turned off after the events were stored: the aggregator still writes nothing.
    UserPreference.objects.create(account_id=me, personalization_off=True)
    aggregate.aggregate(*_window())
    assert _rows(me) == []


def test_synthetic_and_test_actors_are_skipped_unless_allowed(client_for, settings):
    settings.INTEL_ACCEPT_SYNTHETIC = True
    from intel import origin

    seed, tester = acct(), acct()
    SyntheticAccount.objects.create(account_id=seed, label="seed-r3b")
    SyntheticAccount.objects.create(account_id=tester, label="test-r3b")
    origin.clear_cache()
    for who in (seed, tester):
        _send(client_for(who), ev("feed_impression", f"post:{uuid.uuid4()}"))
    aggregate.aggregate(*_window())
    assert _rows(seed) == [] and _rows(tester) == []
    settings.INTEL_SYNTHETIC_IN_RANKING = True
    aggregate.aggregate(*_window())
    assert [r["data_origin"] for r in _rows(seed)] == ["synthetic"]
    assert [r["data_origin"] for r in _rows(tester)] == ["test"]


def test_events_before_reset_at_are_ignored(client_for):
    """Applies once ``intel_user_preference.reset_at`` exists (07 WP 8.4-B2); until
    then the column check keeps the job working."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = "
            "'intel_user_preference' AND column_name = 'reset_at'"
        )
        has = cur.fetchone() is not None
    me = acct()
    item = str(uuid.uuid4())
    _send(client_for(me), ev("feed_impression", f"post:{item}"))
    if not has:
        assert aggregate._has_reset_at() is False
        aggregate.aggregate(*_window())
        assert len(_rows(me)) == 1
        return
    UserPreference.objects.update_or_create(
        account_id=me, defaults={"reset_at": timezone.now() + timedelta(seconds=1)}
    )
    aggregate.aggregate(*_window())
    assert _rows(me) == []


def test_watermark_advances_and_overlaps(client_for):
    me = acct()
    _send(client_for(me), ev("feed_impression", f"post:{uuid.uuid4()}"))
    now = timezone.now() + timedelta(seconds=2)
    aggregate.run(now)
    assert cache.get(aggregate.WATERMARK_KEY) == now.timestamp()
    assert len(_rows(me)) == 1
    out = aggregate.run(now + timedelta(seconds=60))
    assert out["lo"] == (now - aggregate.OVERLAP).isoformat()
