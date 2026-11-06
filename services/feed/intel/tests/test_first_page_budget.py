"""R3 WP A8 (09 R3, 02 section 22): the first-page query budget under home@2c.

Counted with ``CaptureQueriesContext`` on a world with connections, a joined group,
a followed account's public posts, recommended pool items and a viewer history
(ledger records, a durable engagement row): a ``for_you`` first page reads at most
``FIRST_PAGE_READS`` queries, plus exactly 2 writes on a new visit (the visit row and
the close of the previous one) and 0 otherwise; a next page at most 5; a peek, a
chronological first page and a reused frozen list stay small too. Nothing is cached
across requests to get there: eligibility is read fresh on every page."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from feed.models import PostStats, ReactionState

from intel import discovery, exposure, hot
from intel.models import RankingConfig
from intel.tests import world as w
from intel.tests.helpers import ADULT_CLAIMS, client_with_claims

pytestmark = pytest.mark.django_db

FIRST_PAGE_READS = 12
NEXT_PAGE = 5
WRITES = ("INSERT", "UPDATE", "DELETE")


@pytest.fixture(autouse=True)
def _no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


def _activate(label):
    from intel.config import store

    store.activate("home", RankingConfig.objects.get(surface="home", note=label).version)


def _ago(**kw):
    return w.NOW - (timezone.now() - timedelta(**kw))


def _world():
    viewer = w.uid()
    for i in range(40):
        friend = w.uid()
        w.friends(viewer, friend)
        p = w.post(friend, age=_ago(minutes=10 + i * 17))
        w.feed_row(viewer, p, friend)
        PostStats.objects.create(post_id=p, reactions=i % 5, comments=i % 3)
    group = w.group(owner=w.uid())
    w.member(viewer, group)
    for _ in range(5):
        w.post(w.uid(), audience="group", group=group, age=_ago(hours=2))
    followed = w.uid()
    w.follow(viewer, followed)
    for i in range(5):
        w.post(followed, age=_ago(hours=3 + i))
    for i in range(20):
        p = w.post(w.uid(), age=_ago(hours=1, minutes=i))
        ReactionState.objects.create(post_id=p, reactor_id=w.uid(), active=True, occurred_at=w.NOW)
    return viewer


class Clock:
    def __init__(self, monkeypatch, start):
        self.now = start
        monkeypatch.setattr("feed.views.clock.request_now", lambda request, account: self.now)


# Transaction control (``ATOMIC_REQUESTS`` savepoints in the test transaction) is not
# a query of the page.
CONTROL = ("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")


def _split(queries):
    sql = [q["sql"].lstrip() for q in queries if not q["sql"].lstrip().upper().startswith(CONTROL)]
    writes = [q for q in sql if q.upper().startswith(WRITES)]
    reads = [q for q in sql if not q.upper().startswith(WRITES)]
    return reads, writes


def _warm(viewer):
    """The viewer's age class is memoised (WP 4b.14, once per account, not per page)."""
    from intel import age

    age.capture(viewer, ADULT_CLAIMS)


def _get(client, **params):
    with CaptureQueriesContext(connection) as q:
        resp = client.get("/api/v1/feed/", {"mode": "for_you", **params})
    assert resp.status_code == 200, resp.content
    return resp.json(), _split(q.captured_queries)


def _history(viewer, post_ids):
    th = exposure.thresholds()
    minute = int(datetime.now(UTC).timestamp() // 60) - 90
    records = [exposure.Record(p, exposure.STATE_VIEWED, minute) for p in post_ids]
    assert exposure.append_batch(viewer, records, th, now=minute * 60)


def _show(label, reads, writes):
    return f"{label}: {len(reads)} reads, {len(writes)} writes\n" + "\n".join(
        f"  {sql[:160]}" for sql in reads + writes
    )


def test_first_page_budget_under_home_2c(client_for, redis_hot, monkeypatch):
    _activate("home@2c-r15")
    discovery.rebuild()
    viewer = _world()
    _warm(viewer)
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    clock = Clock(monkeypatch, datetime.now(UTC).replace(microsecond=0))

    body, (reads, writes) = _get(client, entry="load")
    assert body["meta"]["visit"]["kind"] == "new"
    assert len(reads) <= FIRST_PAGE_READS, _show("first visit", reads, writes)
    assert len(writes) == 1, _show("first visit", reads, writes)  # nothing to close yet

    _history(viewer, [i["post_id"] for i in body["data"][:8]])
    clock.now += timedelta(seconds=30)
    body, (reads, writes) = _get(client, entry="pull")
    assert body["meta"]["visit"]["kind"] == "refresh"
    assert len(reads) <= FIRST_PAGE_READS, _show("refresh", reads, writes)
    assert writes == [], _show("refresh", reads, writes)

    clock.now += timedelta(minutes=10)
    body, (reads, writes) = _get(client, entry="return")
    assert body["meta"]["visit"]["kind"] == "ongoing"
    assert len(reads) <= FIRST_PAGE_READS and writes == [], _show("ongoing", reads, writes)

    cursor = body["page"]["next_cursor"]
    body, (reads, writes) = _get(client, cursor=cursor)
    assert len(reads) <= NEXT_PAGE and writes == [], _show("next page", reads, writes)

    clock.now += timedelta(minutes=45)
    body, (reads, writes) = _get(client, entry="load")
    assert body["meta"]["visit"]["kind"] == "new"
    assert len(reads) <= FIRST_PAGE_READS, _show("new visit", reads, writes)
    assert len(writes) == 2, _show("new visit", reads, writes)


def test_reload_peek_and_chronological_pages_stay_small(client_for, redis_hot, monkeypatch):
    _activate("home@2c")
    viewer = _world()
    _warm(viewer)
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    clock = Clock(monkeypatch, datetime.now(UTC).replace(microsecond=0))
    _get(client, entry="load")
    clock.now += timedelta(seconds=20)
    body, (reads, writes) = _get(client, entry="reload")
    assert body["meta"]["visit"]["kind"] == "refresh"
    assert len(reads) <= NEXT_PAGE + 1 and writes == [], _show("reload", reads, writes)

    with CaptureQueriesContext(connection) as q:
        resp = client.get(
            "/api/v1/feed/",
            {"mode": "for_you", "peek": "1", "since": (clock.now - timedelta(hours=2)).isoformat()},
        )
    assert resp.status_code == 200
    reads, writes = _split(q.captured_queries)
    assert len(reads) <= FIRST_PAGE_READS and writes == [], _show("peek", reads, writes)

    clock.now += timedelta(hours=1)
    with CaptureQueriesContext(connection) as q:
        resp = client.get("/api/v1/feed/", {"mode": "recent", "entry": "load"})
    assert resp.json()["meta"]["visit"]["kind"] == "new"
    reads, writes = _split(q.captured_queries)
    assert len(reads) <= 6 and len(writes) == 2, _show("recent new visit", reads, writes)


def test_personalization_off_reads_no_visit_and_writes_nothing(client_for, redis_hot):
    from intel.models import FeedSession, UserPreference

    _activate("home@2c")
    viewer = _world()
    UserPreference.objects.create(account_id=viewer, personalization_off=True)
    _warm(viewer)
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    body, (reads, writes) = _get(client, entry="load")
    assert body["meta"]["visit"] is None
    assert writes == [] and not FeedSession.objects.filter(account_id=viewer).exists()
    assert not hot.raw_client().exists(hot.hot().make_key(hot.visit_key(viewer)))
    assert not hot.raw_client().exists(hot.hot().make_key(exposure.ledger_key(viewer)))
    assert not hot.raw_client().exists(hot.hot().make_key(hot.head_key("home", viewer)))
