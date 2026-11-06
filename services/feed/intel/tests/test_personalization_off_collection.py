"""R3 WP 4b.16 (owner decision 24): with personalization off, ingest stores nothing.

A batch carrying every client event type leaves 0 rows in SQL (no
``intel_signal_event``, no ``intel_signal_batch``) and makes 0 Redis writes (no
ledger record, no visit-hash update), and the check costs no extra query: the
gate is inside the batch-claim statement."""

import json
import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from intel import exposure, hot
from intel.models import CLIENT_EVENT_TYPES, EventType, UserPreference
from intel.ranking import serve_tokens as st

from .helpers import acct, batch, ev, signal_rows

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/signals/"


def _every_type(me) -> list[dict]:
    post, video, reel = (str(uuid.uuid4()) for _ in range(3))
    token = st.issue(me, "post", post, "home", reason="recent")
    events = [
        ev("feed_impression", f"post:{post}", st=token),
        ev("post_open", f"post:{post}"),
        ev("feed_dwell", f"post:{post}", dwell_ms=9_000),
        ev("video_start", f"video:{video}", play_index=1),
        ev("video_progress", f"video:{video}", watch_ms=5_000, pos_ms=5_000),
        ev("video_complete", f"video:{video}", watch_ms=20_000),
        ev("video_rewatch", f"video:{video}", play_index=2),
        ev("video_skip", f"video:{uuid.uuid4()}", watch_ms=300),
        ev("reel_view", f"reel:{reel}", watch_ms=4_000),
        ev("profile_visit", f"profile:{uuid.uuid4()}"),
    ]
    assert {e["t"] for e in events} == {str(t) for t in CLIENT_EVENT_TYPES}
    return events


class _Spy:
    """Counts every command sent to redis-hot (reads included)."""

    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def __getattr__(self, name):
        target = getattr(self.inner, name)
        if not callable(target):
            return target

        def call(*a, **k):
            self.calls.append(name)
            return target(*a, **k)

        return call


def _batch_rows(account_id) -> int:
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM intel_signal_batch WHERE account_id = %s", [account_id])
        return cur.fetchone()[0]


def _keys(backend) -> dict:
    client = hot.raw_client()
    return {k: client.dump(k) for k in client.scan_iter(match=backend.make_key("*"))}


def test_personalization_off_stores_nothing_sql_and_redis(redis_hot, client_for, monkeypatch):
    me = acct()
    UserPreference.objects.create(account_id=me, personalization_off=True)
    sess = redis_hot.make_key(hot.visit_key(me))
    hot.raw_client().hset(sess, mapping={"visit_ord": "3", "last_activity_at": "1", "dc": "0"})
    before = _keys(redis_hot)
    spy = _Spy(hot.raw_client())
    monkeypatch.setattr(hot, "raw_client", lambda: spy)
    events = _every_type(me)
    with CaptureQueriesContext(connection) as q:
        resp = client_for(me).post(
            URL, data=json.dumps(batch(*events)), content_type="application/json"
        )
    assert resp.status_code == 202
    assert resp.json()["data"] == {
        "accepted": 0,
        "duplicate": False,
        "rejected": {"personalization_off": len(events)},
    }
    assert signal_rows(account_id=me) == []
    assert _batch_rows(me) == 0
    assert spy.calls == []  # 0 Redis commands of any kind
    monkeypatch.undo()
    assert _keys(redis_hot) == before  # the visit hash untouched, no ledger key
    assert hot.raw_client().exists(redis_hot.make_key(exposure.ledger_key(me))) == 0
    # The gate is the claim statement itself: no extra query for it.
    claims = [s for s in (x["sql"] for x in q.captured_queries) if "intel_signal_batch" in s]
    assert len(claims) == 1 and "personalization_off" in claims[0]
    assert not [
        x
        for x in q.captured_queries
        if "intel_user_preference" in x["sql"] and "intel_signal_batch" not in x["sql"]
    ]


def test_personalization_on_again_collects_again(redis_hot, client_for):
    me = acct()
    UserPreference.objects.create(account_id=me, personalization_off=True)
    client = client_for(me)
    post = f"post:{uuid.uuid4()}"
    body = batch(ev("feed_impression", post))
    client.post(URL, data=json.dumps(body), content_type="application/json")
    UserPreference.objects.filter(account_id=me).update(personalization_off=False)
    # The same batch id is not burnt: nothing was claimed while off.
    resp = client.post(URL, data=json.dumps(body), content_type="application/json")
    assert resp.json()["data"]["accepted"] == 1
    assert [r["event_type"] for r in signal_rows(account_id=me)] == [EventType.FEED_IMPRESSION]
    assert len(exposure.load(me, 0)) == 1


def test_ingest_queries_per_batch(client_for):
    """07 WP 4b.16: the conditional insert + 1 COPY (no video events here), and the
    partition check the COPY always needed; nothing else."""
    me = acct()
    events = [ev("feed_impression", f"post:{uuid.uuid4()}") for _ in range(50)]
    client = client_for(me)
    client.post(URL, data=json.dumps(batch(events[0])), content_type="application/json")
    with CaptureQueriesContext(connection) as q:
        client.post(URL, data=json.dumps(batch(*events)), content_type="application/json")
    sqls = [x["sql"] for x in q.captured_queries]
    reads = [s for s in sqls if s.lstrip().upper().startswith("SELECT")]
    assert len([s for s in sqls if "intel_signal_batch" in s]) == 1
    assert len([s for s in sqls if "COPY" in s.upper()]) == 1
    assert not [s for s in reads if "intel_signal_event" in s]


def test_switching_personalization_off_purges_and_then_stores_nothing(
    redis_hot, client_for, monkeypatch, django_capture_on_commit_callbacks
):
    """R4 (R3 open item 4): turning personalization off in My Algorithm purges the
    account's behavioural keys and visit rows in the same request flow, and from then
    on a first page, a later page, a telemetry batch and the bus write 0 SQL rows, 0
    Redis keys and no bus rows (the age-class memo, safety data, is the only key)."""
    from feed.models import FeedItem

    from intel.handlers import intel_on_post_reacted
    from intel.models import FeedSession
    from tara_events.envelope import EventEnvelope

    from . import world as w

    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    me = acct()
    for _i in range(12):
        friend = acct()
        w.feed_row(me, w.post(friend), friend)
    client = client_for(me)
    client.get("/api/v1/feed/", {"mode": "for_you"})  # a visit, a session, a head
    assert FeedSession.objects.filter(account_id=me).exists()
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.patch(
            "/api/v1/feed/preferences/", {"personalization_off": True}, format="json"
        )
    assert resp.status_code == 200
    keys = lambda: [  # noqa: E731
        k for k in hot.behaviour_keys(me) if hot.raw_client().exists(redis_hot.make_key(k))
    ]
    assert keys() == [] and not FeedSession.objects.filter(account_id=me).exists()
    signal_before = len(signal_rows(account_id=me))
    first = client.get("/api/v1/feed/", {"mode": "for_you", "limit": 5}).json()
    assert first["meta"]["personalization_off"] is True and first["meta"]["visit"] is None
    client.get(
        "/api/v1/feed/", {"mode": "for_you", "limit": 5, "cursor": first["page"]["next_cursor"]}
    )
    client.post(
        URL,
        data=json.dumps(batch(ev("post_open", f"post:{first['data'][0]['post_id']}"))),
        content_type="application/json",
    )
    post_id = str(FeedItem.objects.filter(recipient_id=me).first().post_id)
    intel_on_post_reacted(
        EventEnvelope(
            event_type="post.reacted",
            subject_id=post_id,
            producer="test",
            payload={"post_id": post_id, "reactor": me, "author_id": acct()},
        )
    )
    client.post("/api/v1/feed/hide/", {"post_id": post_id, "reason": "not_interested"})
    assert keys() == []
    assert len(signal_rows(account_id=me)) == signal_before
    assert not FeedSession.objects.filter(account_id=me).exists()
