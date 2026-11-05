"""WP 2.3 local benchmark: ``POST /feed/signals/`` with 50 events, p95 <= 30 ms.

Not collected by default (``bench_*``). Run it explicitly:

    python -m pytest -q -s intel/tests/bench_ingest.py

It measures ``ingest()`` (validation, the batch insert, the session read and the
``COPY``: the server work the budget in 02 section 22 is about) and, for
reference, the whole request through DRF with JWT authentication.
"""

import json
import statistics
import time
import uuid

import pytest
from django.db import connection

from intel.signals import ingest

from .helpers import acct, batch, ev

pytestmark = pytest.mark.django_db
RUNS = 60
BUDGET_MS = 30.0


def _batch_of_50(session):
    events = []
    for i in range(25):
        item = f"post:{uuid.uuid4()}"
        events.append(ev("feed_impression", item, pos=i))
        events.append(ev("post_open", item) if i % 2 else ev("video_start", item, play_index=1))
    return batch(*events, session=session)


def _p95(samples):
    return statistics.quantiles(samples, n=20)[18]


def test_ingest_p95_for_50_events(client_for):
    me, session = acct(), str(uuid.uuid4())
    service, http = [], []
    for _ in range(RUNS):
        body = _batch_of_50(session)
        parsed = {**body, "batch_id": uuid.UUID(body["batch_id"]), "session_id": uuid.UUID(session)}
        start = time.perf_counter()
        result = ingest.ingest(me, parsed)
        service.append((time.perf_counter() - start) * 1000)
        assert result.accepted == 50
    client = client_for(me)
    for _ in range(RUNS):
        raw = json.dumps(_batch_of_50(session))
        start = time.perf_counter()
        resp = client.post("/api/v1/feed/signals/", data=raw, content_type="application/json")
        http.append((time.perf_counter() - start) * 1000)
        assert resp.status_code == 202
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM intel_signal_event WHERE account_id = %s", [me])
        stored = cur.fetchone()[0]
    print(
        f"\ningest(): p50 {statistics.median(service):.1f} ms, p95 {_p95(service):.1f} ms; "
        f"HTTP+JWT: p50 {statistics.median(http):.1f} ms, p95 {_p95(http):.1f} ms; "
        f"rows {stored} ({RUNS * 2} batches x 50)"
    )
    assert stored == RUNS * 2 * 50
    assert _p95(service) <= BUDGET_MS
