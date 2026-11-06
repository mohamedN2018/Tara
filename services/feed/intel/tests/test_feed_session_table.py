"""R3 WP A3 (07 WP 4b.4, 06 sections 4.3 and 13): ``intel_feed_session``.

One row per visit, written at the visit start and closed lazily at the next one with
the counters of ``feed:sess``; **2 SQL writes on a new-visit first page, 0 on a
refresh, an ongoing first page and every next page**; deleted on account deletion and
after ``session.feed_session_retention_d`` days; never an item id."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from intel import deletion, hot, tasks
from intel.models import FeedSession
from intel.tests import world as w

pytestmark = pytest.mark.django_db
WRITES = ("INSERT", "UPDATE", "DELETE")


@pytest.fixture(autouse=True)
def _no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


class Clock:
    def __init__(self, monkeypatch, start):
        self.now = start
        monkeypatch.setattr("feed.views.clock.request_now", lambda request, account: self.now)

    def move(self, **kw):
        self.now += timedelta(**kw)


def _writes(queries, table="intel_feed_session") -> list[str]:
    return [
        q["sql"]
        for q in queries
        if q["sql"].lstrip().upper().startswith(WRITES) and table in q["sql"]
    ]


def _all_writes(queries) -> list[str]:
    return [q["sql"] for q in queries if q["sql"].lstrip().upper().startswith(WRITES)]


def _viewer(n=25):
    viewer, friend = w.uid(), w.uid()
    for i in range(n):
        w.feed_row(viewer, w.post(friend, age=timedelta(hours=1, minutes=i)), friend)
    return viewer


def _first(client, mode="for_you", **params):
    with CaptureQueriesContext(connection) as q:
        body = client.get("/api/v1/feed/", {"mode": mode, **params}).json()
    return body, q.captured_queries


@pytest.mark.parametrize("mode", ["for_you", "recent"])
def test_one_row_per_visit_closed_with_the_counters(client_for, redis_hot, monkeypatch, mode):
    viewer = _viewer()
    client = client_for(viewer)
    clock = Clock(monkeypatch, datetime.now(UTC).replace(microsecond=0))
    body, q = _first(client, mode, entry="load")
    assert body["meta"]["visit"]["kind"] == "new"
    assert len(_writes(q)) == 1  # the first visit ever: nothing to close
    first = FeedSession.objects.get(account_id=viewer)
    assert (first.kind, first.first_pages, first.ended_at) == ("new", 1, None)

    clock.move(seconds=30)
    body, q = _first(client, mode, entry="pull")
    assert body["meta"]["visit"]["kind"] == "refresh"
    assert _writes(q) == [] and _all_writes(q) == []
    clock.move(minutes=10)
    body, q = _first(client, mode, entry="nav")
    assert body["meta"]["visit"]["kind"] == "ongoing"
    assert _all_writes(q) == []
    cursor = body["page"]["next_cursor"]
    with CaptureQueriesContext(connection) as nq:
        client.get("/api/v1/feed/", {"mode": mode, "cursor": cursor})
    assert _all_writes(nq.captured_queries) == []

    # Ingest (track B) counts displays and consumptions in the hash meanwhile.
    key = hot.hot().make_key(hot.visit_key(viewer))
    hot.raw_client().hincrby(key, "dc", 6)
    hot.raw_client().hincrby(key, "cc", 2)

    clock.move(minutes=45)
    body, q = _first(client, mode, entry="load")
    assert body["meta"]["visit"]["kind"] == "new"
    assert len(_writes(q)) == 2  # INSERT the new visit, UPDATE (close) the previous
    assert len(_all_writes(q)) == 2
    rows = list(FeedSession.objects.filter(account_id=viewer).order_by("started_at"))
    assert len(rows) == 2
    closed, current = rows
    assert closed.ended_at is not None and current.ended_at is None
    assert (closed.first_pages, closed.refreshes, closed.displayed, closed.consumed) == (
        3,
        1,
        6,
        2,
    )
    assert body["meta"]["visit"]["since"] == closed.started_at.isoformat()
    columns = {f.column for f in FeedSession._meta.fields}
    assert not any("item" in c or "post" in c for c in columns)  # never item ids


def test_a_redis_miss_closes_the_latest_row(client_for, redis_hot, monkeypatch):
    viewer = _viewer(5)
    client = client_for(viewer)
    clock = Clock(monkeypatch, datetime.now(UTC).replace(microsecond=0))
    _first(client, entry="load")
    hot.raw_client().delete(hot.hot().make_key(hot.visit_key(viewer)))  # expired
    clock.move(hours=26)
    body, q = _first(client, entry="load")
    assert body["meta"]["visit"]["kind"] == "returning"
    assert len(_writes(q)) == 2
    assert FeedSession.objects.filter(account_id=viewer, ended_at__isnull=False).count() == 1


def test_rows_go_with_the_account(client_for, redis_hot, monkeypatch):
    viewer = _viewer(3)
    client = client_for(viewer)
    clock = Clock(monkeypatch, datetime.now(UTC))
    _first(client)
    clock.move(hours=2)
    _first(client)
    assert FeedSession.objects.filter(account_id=viewer).count() == 2
    deletion.erase_account(viewer)
    assert not FeedSession.objects.filter(account_id=viewer).exists()
    assert not hot.raw_client().exists(hot.hot().make_key(hot.visit_key(viewer)))


def test_retention_purges_old_rows_nightly(settings):
    viewer = w.uid()
    now = datetime.now(UTC)
    for days in (1, 29, 31, 45):
        FeedSession.objects.create(
            id=uuid.uuid4(),
            account_id=viewer,
            kind="new",
            entry_surface="home",
            started_at=now - timedelta(days=days),
            last_activity_at=now - timedelta(days=days),
            data_origin="test",
        )
    assert tasks.purge_feed_sessions() == 2
    assert FeedSession.objects.filter(account_id=viewer).count() == 2
    assert settings.CELERY_BEAT_SCHEDULE["intel-purge-feed-sessions"]["task"] == (
        "intel.purge_feed_sessions"
    )


def test_a_refused_hash_write_is_counted_and_the_page_is_served(client_for, redis_hot, monkeypatch):
    from intel import metrics

    viewer = _viewer(3)
    client = client_for(viewer)
    Clock(monkeypatch, datetime.now(UTC))
    seen = []
    monkeypatch.setattr(metrics, "hot_write_failed", lambda key: seen.append(key))
    real = hot.raw_client

    class Refusing:
        """redis-hot full (noeviction): reads work, the visit's MULTI write is refused."""

        def __init__(self, inner):
            self.inner = inner

        def pipeline(self, transaction=True):
            pipe = self.inner.pipeline(transaction=transaction)
            if transaction:

                def refuse():
                    raise RuntimeError("OOM command not allowed when used memory > 'maxmemory'")

                pipe.execute = refuse
            return pipe

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr(hot, "raw_client", lambda: Refusing(real()))
    resp = client.get("/api/v1/feed/", {"mode": "for_you"})
    assert resp.status_code == 200 and resp.json()["data"]
    assert "sess" in seen
    # The SQL half still commits: the visit row exists.
    assert FeedSession.objects.filter(account_id=viewer).count() == 1
