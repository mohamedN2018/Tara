"""R3 WP A3 (07 WP 4b.4, 06 section 4.2): the visit classifier.

Clock-driven table test on server timestamps only: refresh, ongoing, new, returning,
lapsed, a reload and a new tab (new ``sid``) inside 30 minutes, and forged hints that
cannot turn an idle gap into a refresh or change eligibility. Then the API: the hash
fields of the track-B contract, ``meta.visit``, the Redis-miss SQL fallback and
``personalization_off`` (nothing stored, ``meta.visit`` null)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from intel import config, hot, session_ctx
from intel.models import FeedSession, UserPreference
from intel.tests import world as w

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
CFG = config.from_params("home", {})
S = CFG.section("session")


def _state(*, last, started, fp=None, prev=None, ord_=3, surface="home"):
    h = {
        "visit_id": uuid.uuid4().hex,
        "visit_ord": str(ord_),
        "kind": "new",
        "visit_started_at": str(int(started.timestamp())),
        "last_activity_at": str(int(last.timestamp())),
        "fp": "2",
        "rf": "1",
        "dc": "7",
        "cc": "2",
    }
    if fp is not None:
        h[f"fp:{surface}"] = str(int(fp.timestamp()))
    if prev is not None:
        h["prev_visit_started_at"] = str(int(prev.timestamp()))
    return h


def _kind(now, state, entry=None, sid=None):
    return session_ctx.classify(w.uid(), "home", now, CFG, entry=entry, sid=sid, state=state)


CASES = [
    # (label, seconds since: the last first page here, the last activity, the visit
    # start; entry; kind)
    ("refresh by gap", 30, 30, 600, None, "refresh"),
    ("reload inside the visit", 900, 900, 1200, "reload", "refresh"),
    ("pull inside the visit", 1700, 1700, 3000, "pull", "refresh"),
    ("legacy refresh = pull", 1700, 1700, 3000, "refresh", "refresh"),
    ("back via navigation", 900, 900, 1200, "nav", "ongoing"),
    ("legacy open = nav", 900, 900, 1200, "open", "ongoing"),
    ("idle 45 min, visit 2 h old", 2700, 2700, 7200, None, "new"),
    ("idle 45 min, forged reload", 2700, 2700, 7200, "reload", "new"),
    ("idle, visit started 25 h ago", 3 * 3600, 3 * 3600, 25 * 3600, None, "returning"),
    ("idle, visit started 8 d ago", 8 * 86400, 8 * 86400, 8 * 86400, "pull", "lapsed"),
]


@pytest.mark.parametrize(("label", "fp_ago", "last_ago", "start_ago", "entry", "kind"), CASES)
def test_kinds_follow_the_server_thresholds(label, fp_ago, last_ago, start_ago, entry, kind):
    state = _state(
        last=T0 - timedelta(seconds=last_ago),
        started=T0 - timedelta(seconds=start_ago),
        fp=T0 - timedelta(seconds=fp_ago),
    )
    assert _kind(T0, state, entry).kind == kind, label


def test_the_thresholds_come_from_the_config():
    assert (S["refresh_max_s"], S["ongoing_idle_s"]) == (120, 1800)
    assert (S["returning_after_h"], S["lapsed_after_d"]) == (24, 7)
    edge = T0 - timedelta(seconds=S["ongoing_idle_s"])
    state = _state(last=edge, started=edge)
    assert _kind(T0, state).kind == "new"  # exactly at the idle threshold: idle
    state = _state(last=edge + timedelta(seconds=1), started=edge)
    assert _kind(T0, state).kind == "ongoing"


def test_a_new_tab_inside_30_minutes_is_not_a_new_visit():
    state = _state(last=T0 - timedelta(minutes=10), started=T0 - timedelta(minutes=20))
    state["sid"] = uuid.uuid4().hex
    visit = _kind(T0, state, entry="load", sid=uuid.uuid4().hex)  # another tab's sid
    assert visit.kind == "ongoing" and not visit.is_new


def test_the_first_visit_ever_is_new_without_since():
    visit = session_ctx.classify(w.uid(), "home", T0, CFG, entry=None, sid=None, state={})
    assert (visit.kind, visit.since, visit.visit_ord) == ("new", None, 0)


def test_last_visit_moves_only_on_a_new_visit():
    started, prev = T0 - timedelta(hours=2), T0 - timedelta(days=1)
    state = _state(last=T0 - timedelta(minutes=5), started=started, prev=prev)
    ongoing = _kind(T0, state)
    assert ongoing.since == prev  # unchanged during the visit
    idle = _state(last=T0 - timedelta(hours=1), started=started, prev=prev, ord_=31)
    new = _kind(T0, idle)
    assert new.kind == "new" and new.since == started  # the current visit's start
    assert new.visit_ord == 0  # mod 32


def test_since_is_clamped_to_max_age():
    started = T0 - timedelta(days=20)
    visit = _kind(T0, _state(last=started, started=started))
    assert visit.kind == "lapsed"
    assert visit.since == T0 - timedelta(hours=S["new_since"]["max_age_h"])


def test_a_redis_miss_reads_the_latest_visit_row_once():
    viewer = w.uid()
    FeedSession.objects.create(
        id=uuid.uuid4(),
        account_id=viewer,
        kind="new",
        entry_surface="home",
        started_at=T0 - timedelta(minutes=20),
        last_activity_at=T0 - timedelta(minutes=20),
        data_origin="test",
    )
    with CaptureQueriesContext(connection) as q:
        visit = session_ctx.classify(viewer, "home", T0, CFG, entry=None, sid=None, state={})
    assert len(q) == 1
    assert visit.kind == "ongoing" and visit.from_sql


# ---- through the API ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


def _at(monkeypatch, when):
    monkeypatch.setattr("feed.views.clock.request_now", lambda request, account: when)


def _viewer_with_posts(n=3):
    viewer, friend = w.uid(), w.uid()
    for i in range(n):
        w.feed_row(viewer, w.post(friend, age=timedelta(hours=1 + i)), friend)
    return viewer


def _hash(viewer):
    raw = hot.raw_client().hgetall(hot.hot().make_key(hot.visit_key(viewer)))
    return session_ctx.decode_hash(raw)


@pytest.mark.parametrize("mode", ["recent", "for_you"])
def test_the_hash_carries_the_contract_fields(client_for, redis_hot, monkeypatch, mode):
    viewer = _viewer_with_posts()
    client = client_for(viewer)
    now = datetime.now(UTC).replace(microsecond=0)
    _at(monkeypatch, now)
    sid = str(uuid.uuid4())
    body = client.get("/api/v1/feed/", {"mode": mode, "entry": "load", "sid": sid}).json()
    h = _hash(viewer)
    for name in (
        "visit_id",
        "visit_ord",
        "kind",
        "visit_started_at",
        "last_activity_at",
        "sid",
        "fp:home",
        "fp",
        "rf",
        "dc",
        "cc",
    ):
        assert name in h, name
    assert h["sid"] == uuid.UUID(sid).hex and h["fp"] == "1"
    assert int(h["visit_started_at"]) == int(now.timestamp())
    ttl = hot.raw_client().ttl(hot.hot().make_key(hot.visit_key(viewer)))
    assert 0 < ttl <= session_ctx.TTL_S
    visit = body["meta"]["visit"]
    assert visit["kind"] == "new" and visit["min_to_show"] == 3
    assert body["meta"]["refresh_after_s"] == 600
    assert body["meta"]["auto_refetch_after_s"] == 1800
    # A refresh 30 s later counts in the same hash.
    _at(monkeypatch, now + timedelta(seconds=30))
    body = client.get("/api/v1/feed/", {"mode": mode, "entry": "pull"}).json()
    assert body["meta"]["visit"]["kind"] == "refresh"
    assert (_hash(viewer)["fp"], _hash(viewer)["rf"]) == ("2", "1")


def test_a_forged_entry_cannot_change_eligibility(client_for, redis_hot, monkeypatch):
    viewer, friend, stranger = w.uid(), w.uid(), w.uid()
    w.feed_row(viewer, w.post(friend), friend)
    w.block(viewer, stranger)
    w.feed_row(viewer, w.post(stranger), stranger)  # a stale row of a blocked author
    client = client_for(viewer)
    _at(monkeypatch, datetime.now(UTC))
    seen = set()
    for entry in session_ctx.ENTRIES:
        body = client.get(
            "/api/v1/feed/", {"mode": "for_you", "entry": entry, "sid": str(uuid.uuid4())}
        ).json()
        seen |= {i["author_id"] for i in body["data"]}
    assert stranger not in seen and friend in seen


def test_an_unknown_entry_or_sid_is_refused(client_for):
    client = client_for(w.uid())
    assert client.get("/api/v1/feed/", {"entry": "teleport"}).status_code == 400
    assert client.get("/api/v1/feed/", {"sid": "not-a-uuid"}).status_code == 400


@pytest.mark.parametrize("mode", ["recent", "for_you"])
def test_personalization_off_stores_nothing(client_for, redis_hot, monkeypatch, mode):
    viewer = _viewer_with_posts()
    UserPreference.objects.create(account_id=viewer, personalization_off=True)
    client = client_for(viewer)
    _at(monkeypatch, datetime.now(UTC))
    before = set(hot.raw_client().scan_iter(match=hot.hot().make_key("*")))
    for entry in ("load", "reload", "pull"):
        body = client.get("/api/v1/feed/", {"mode": mode, "entry": entry}).json()
        assert body["meta"]["visit"] is None
    after = set(hot.raw_client().scan_iter(match=hot.hot().make_key("*")))
    ours = {k for k in after - before if str(viewer).encode() in k}
    # Allowed: the ranking session pager (WP 4.10, no behaviour) and the account's own
    # age-class memo (safety data, WP 4b.14). No visit, ledger or head key.
    assert all(b"feed:rank:" in k or b"intel:age:" in k for k in ours), ours
    assert not FeedSession.objects.filter(account_id=viewer).exists()
