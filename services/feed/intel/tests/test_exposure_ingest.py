"""R3 WP 4b.3: the exposure ledger written by ``POST /feed/signals/`` (feed-signals).

States from each event type, nothing from served-only items, the visit stamp and the
visit-hash updates, compaction at the threshold, the size bounds, the test clock, and
fail-soft under a refusing (OOM) redis-hot."""

import json
import uuid
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from feed.models import FeedItem

from intel import clock, exposure, hot, metrics
from intel.models import SyntheticAccount
from intel.ranking import serve_tokens as st

from .helpers import acct, batch, ev, signal_rows

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/signals/"


def _send(client, *events, **kw):
    return client.post(URL, data=json.dumps(batch(*events, **kw)), content_type="application/json")


def _raw(viewer):
    return hot.raw_client().get(hot.hot().make_key(exposure.ledger_key(viewer))) or b""


def _ledger(viewer, visit=None):
    return exposure.fold(_raw(viewer), visit)


def _p(item):
    return uuid.UUID(str(item)).bytes[:8]


def _sess(viewer, **fields):
    key = hot.hot().make_key(hot.visit_key(viewer))
    hot.raw_client().hset(key, mapping={k: str(v) for k, v in fields.items()})
    return key


def _failed_exp():
    return metrics.HOT_WRITE_FAILED.labels(key="exp")._value.get()


def test_each_event_type_records_its_state(redis_hot, client_for):
    me = acct()
    c = client_for(me)
    shown, opened, skipped, completed, reel, profile = (str(uuid.uuid4()) for _ in range(6))
    resp = _send(
        c,
        ev("feed_impression", f"post:{shown}"),
        ev("feed_impression", f"post:{opened}"),
        ev("post_open", f"post:{opened}"),
        ev("video_skip", f"video:{skipped}", watch_ms=500),
        ev("video_start", f"video:{completed}", play_index=1),
        ev("video_complete", f"video:{completed}", watch_ms=20_000),
        ev("reel_view", f"reel:{reel}", watch_ms=3_000),
        ev("profile_visit", f"profile:{profile}"),
    )
    assert resp.status_code == 202 and resp.json()["data"]["accepted"] == 8
    led = _ledger(me)
    assert led[_p(shown)].state == exposure.STATE_DISPLAYED
    assert led[_p(opened)].state == exposure.STATE_VIEWED
    assert led[_p(skipped)].state == exposure.STATE_SKIPPED
    assert led[_p(completed)].state == exposure.STATE_CONSUMED
    assert led[_p(completed)].dwell_only is False
    assert led[_p(reel)].state == exposure.STATE_VIEWED
    assert _p(profile) not in led  # a profile is not an exposure
    assert len(led) == 5
    ttl = hot.raw_client().ttl(hot.hot().make_key(exposure.ledger_key(me)))
    assert 0 < ttl <= exposure.thresholds().ttl_s


def test_dwell_states_and_length_bucket_scaling(redis_hot, client_for):
    me = acct()
    th = exposure.thresholds()
    short, long_, quick, mid = (str(uuid.uuid4()) for _ in range(4))
    issued = timezone.now().timestamp() - 600
    buckets = list(th.length_buckets)
    tok_short = st.issue(me, "post", short, "home", length_bucket=1, now=issued)
    tok_long = st.issue(me, "post", long_, "home", length_bucket=len(buckets), now=issued)
    dwell = int(th.consumed_dwell_ms * float(buckets[0]["scale"])) + 1  # enough for short only
    assert dwell < th.consumed_ms(len(buckets))
    _send(
        client_for(me),
        ev("feed_dwell", f"post:{short}", st=tok_short, dwell_ms=dwell),
        ev("feed_dwell", f"post:{long_}", st=tok_long, dwell_ms=dwell),
        ev("feed_dwell", f"post:{quick}", dwell_ms=th.skip_dwell_ms - 1),
        ev("feed_dwell", f"post:{mid}", dwell_ms=th.skip_dwell_ms),
    )
    led = _ledger(me)
    assert (led[_p(short)].state, led[_p(short)].dwell_only) == (exposure.STATE_CONSUMED, True)
    expected_long = (
        exposure.STATE_VIEWED if dwell >= th.viewed_dwell_ms else exposure.STATE_DISPLAYED
    )
    assert led[_p(long_)].state == expected_long
    assert led[_p(quick)].state == exposure.STATE_SKIPPED
    assert led[_p(mid)].state == exposure.STATE_DISPLAYED


def test_served_only_items_never_get_a_state(redis_hot, client_for):
    """``retrieved`` (06 section 5.1): a first page serves items and writes no record."""
    me = acct()
    for i in range(3):
        FeedItem.objects.create(
            recipient_id=me,
            post_id=uuid.uuid4(),
            author_id=uuid.uuid4(),
            reason="friend",
            score=0,
            snapshot={"type": "text", "excerpt": "hi", "audience": "public"},
            post_created_at=timezone.now() - timedelta(minutes=i),
        )
    c = client_for(me)
    for mode in ("recent", "for_you"):
        assert c.get("/api/v1/feed/", {"mode": mode}).status_code == 200
    assert _raw(me) == b""
    shown = str(FeedItem.objects.filter(recipient_id=me).first().post_id)
    _send(c, ev("feed_impression", f"post:{shown}"))
    assert set(_ledger(me)) == {_p(shown)}  # only the displayed one


def test_visit_ord_is_stamped_and_reload_is_one_exposure(redis_hot, client_for):
    me, item = acct(), str(uuid.uuid4())
    c = client_for(me)
    _sess(me, visit_ord=7, last_activity_at=1)
    _send(c, ev("feed_impression", f"post:{item}"))
    _send(c, ev("feed_impression", f"post:{item}"))  # a reload re-reporting it
    f = _ledger(me, 7)[_p(item)]
    assert (f.exposures, f.in_visit, f.visit_ord) == (1, True, 7)
    _sess(me, visit_ord=8)
    _send(c, ev("feed_impression", f"post:{item}"))
    f = _ledger(me, 8)[_p(item)]
    assert (f.exposures, f.in_visit) == (2, True)


def test_visit_hash_updates_only_when_it_exists(redis_hot, client_for):
    me, other = acct(), acct()
    key = _sess(me, visit_ord=1, last_activity_at=1, dc=0, cc=0)
    item, done = str(uuid.uuid4()), str(uuid.uuid4())
    _send(
        client_for(me),
        ev("feed_impression", f"post:{item}"),
        ev("feed_impression", f"post:{done}"),
        ev("video_start", f"video:{done}", play_index=1),
        ev("video_complete", f"video:{done}", watch_ms=10_000),
    )
    h = {k.decode(): v.decode() for k, v in hot.raw_client().hgetall(key).items()}
    assert int(h["last_activity_at"]) >= int(timezone.now().timestamp()) - 5
    assert (h["dc"], h["cc"]) == ("2", "1")
    # A later batch with an older clock never lowers last_activity_at.
    hot.raw_client().hset(key, "last_activity_at", str(2**40))
    _send(client_for(me), ev("feed_impression", f"post:{uuid.uuid4()}"))
    assert hot.raw_client().hget(key, "last_activity_at") == str(2**40).encode()
    # No visit hash: none is created (feed owns it), the ledger is still written.
    _send(client_for(other), ev("feed_impression", f"post:{uuid.uuid4()}"))
    assert hot.raw_client().exists(hot.hot().make_key(hot.visit_key(other))) == 0
    assert len(_ledger(other)) == 1


def test_compaction_at_the_threshold_and_size_bounds(redis_hot, client_for):
    me = acct()
    c = client_for(me)
    th = exposure.thresholds()
    sizes = []
    # 5 x cap distinct items, 50 per batch: the log must compact several times.
    for _ in range(th.cap * 5 // 50):
        events = [ev("feed_impression", f"post:{uuid.uuid4()}") for _ in range(50)]
        assert _send(c, *events).status_code == 202
        sizes.append(len(_raw(me)))
    assert max(sizes) <= th.max_bytes == 2 * th.cap * 13  # never above 5.2 KB at cap 200
    assert min(sizes[4:]) >= th.cap * 13 - 50 * 13  # it really compacted (not emptied)
    compacted = exposure.compact(_raw(me), th.cap)
    assert len(compacted) <= th.cap * 13  # <= 2.6 KB


def test_ledger_minutes_follow_the_test_clock(redis_hot, client_for, settings):
    settings.INTEL_TEST_CLOCK_ENABLED = True
    settings.INTEL_ACCEPT_SYNTHETIC = True
    me, item = acct(), str(uuid.uuid4())
    SyntheticAccount.objects.create(account_id=me, label="test-r3b-clock")
    from intel import origin

    origin.clear_cache()
    later = timezone.now() + timedelta(days=3)
    resp = client_for(me).post(
        URL,
        data=json.dumps(batch(ev("feed_impression", f"post:{item}"))),
        content_type="application/json",
        HTTP_X_TARA_TEST_NOW=later.isoformat(),
    )
    assert resp.status_code == 202
    assert clock.HEADER == "X-Tara-Test-Now"
    assert _ledger(me)[_p(item)].minute == exposure.epoch_minute(later)


class _Refusing:
    """A redis-hot at ``maxmemory`` under ``noeviction``: every write is refused."""

    def register_script(self, _source):
        def run(*_a, **_k):
            from redis.exceptions import OutOfMemoryError

            raise OutOfMemoryError("OOM command not allowed when used memory > 'maxmemory'.")

        return run

    def get(self, _key):
        return None


def test_fail_soft_under_oom_returns_202_and_stores_rows(client_for):
    me, item = acct(), str(uuid.uuid4())
    before = _failed_exp()
    with mock.patch.object(hot, "raw_client", return_value=_Refusing()):
        resp = _send(client_for(me), ev("feed_impression", f"post:{item}"))
    assert resp.status_code == 202
    assert resp.json()["data"]["accepted"] == 1
    assert [r["event_type"] for r in signal_rows(account_id=me)] == ["feed_impression"]
    assert _failed_exp() == before + 1


def test_append_records_helper_writes_at_a_simulated_minute(redis_hot):
    viewer, item = acct(), uuid.uuid4()
    minute = exposure.epoch_minute(timezone.now() - timedelta(hours=30))
    assert exposure.append_records(viewer, [(item, exposure.STATE_VIEWED, minute)])
    f = exposure.load(viewer, 0)[item.bytes[:8]]
    assert (f.state, f.minute, f.exposures) == (exposure.STATE_VIEWED, minute, 1)
    assert exposure.append_records(viewer, []) is True
