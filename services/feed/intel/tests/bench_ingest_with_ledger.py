"""R3 WP 4b.3/4b.16 local benchmark: ingest with the gate, the token decode and the
ledger script. Not collected by default (``bench_*``); run it explicitly against a
real Redis:

    python -m pytest -q -s intel/tests/bench_ingest_with_ledger.py

It measures, for a 50-event batch carrying serve tokens v2 (impressions, dwells and
opens on 25 served items):

- ``ingest()`` p95 (the conditional batch claim with the ``personalization_off``
  gate, validation, 50 token decodes, the ``COPY`` and the Lua call): budget 30 ms;
- the ledger size at ``cap`` items compacted (<= 2.6 KB) and the largest size ever
  stored while 5 x cap items stream in (never above 5.2 KB);
- the delay between a displayed item's batch and ``fold()`` seeing it (<= 1 s);
- Redis round trips per batch without a compaction: 1 for the ledger, plus 1 (R4 WP
  6.5-B2) for the session-interest vector when the batch carries consumption-grade
  events (these opens and dwells do): 2.

R4: the tokens carry a primary topic, so the vector update folds topic, format and
creator from the token (no read).
"""

import socket
import statistics
import time
import uuid

import pytest

from intel import exposure, hot
from intel.ranking import serve_tokens as st
from intel.signals import ingest

from .helpers import acct, batch, ev

pytestmark = pytest.mark.django_db
RUNS = 60
BUDGET_MS = 30.0


def _p95(samples):
    return statistics.quantiles(samples, n=20)[18]


def _batch_of_50(me, session):
    events = []
    for i in range(25):
        item = str(uuid.uuid4())
        token = st.issue(
            me, "post", item, "home", position=i, reason="for_you", fmt="text",
            length_bucket=1 + i % 3, author_id=uuid.uuid4(), visit_ord=3,
            now=time.time() - 300, topic_id=1 + i % 5,
        )  # fmt: skip
        events.append(ev("feed_impression", f"post:{item}", st=token))
        if i % 2:
            events.append(ev("feed_dwell", f"post:{item}", st=token, dwell_ms=1000 + 400 * i))
        else:
            events.append(ev("post_open", f"post:{item}", st=token))
    body = batch(*events, session=session)
    return {**body, "batch_id": uuid.UUID(body["batch_id"]), "session_id": uuid.UUID(session)}


class _Counting:
    """The real client, counting the commands sent (round trips)."""

    COMMANDS = frozenset({"evalsha", "eval", "get", "set", "script_load"})

    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    def __getattr__(self, name):
        target = getattr(self.inner, name)
        if name not in self.COMMANDS:
            return target

        def call(*a, **k):
            self.calls += 1
            return target(*a, **k)

        return call


def test_ingest_with_ledger(redis_hot, monkeypatch):
    me, session = acct(), str(uuid.uuid4())
    client = hot.raw_client()
    sess = redis_hot.make_key(hot.visit_key(me))
    client.hset(sess, mapping={"visit_ord": "3", "last_activity_at": "1"})
    th = exposure.thresholds()
    for _ in range(3):  # warm the config, the partitions and the script cache
        ingest.ingest(acct(), _batch_of_50(me, session))
    samples, sizes, round_trips, visible = [], [], [], []
    ledger = redis_hot.make_key(exposure.ledger_key(me))
    for _ in range(RUNS):
        body = _batch_of_50(me, session)
        counting = _Counting(client)
        monkeypatch.setattr(hot, "raw_client", lambda c=counting: c)
        start = time.perf_counter()
        result = ingest.ingest(me, body)
        took = time.perf_counter() - start
        samples.append(took * 1000)
        assert result.accepted == 50
        round_trips.append(counting.calls)
        monkeypatch.undo()
        t0 = time.perf_counter()
        folded = exposure.fold(client.get(ledger), 3)
        last = uuid.UUID(body["events"][-2]["item"].split(":")[1]).bytes[:8]
        assert last in folded
        visible.append(took + time.perf_counter() - t0)
        sizes.append(client.strlen(ledger))
    compacted = exposure.compact(client.get(ledger), th.cap)
    print(
        f"\nhost {socket.gethostname()}: ingest() 50 events p50 "
        f"{statistics.median(samples):.1f} ms, p95 {_p95(samples):.1f} ms, max "
        f"{max(samples):.1f} ms; Redis round trips per batch: median "
        f"{statistics.median(round_trips)}, max {max(round_trips)} (compactions); ledger "
        f"bytes max {max(sizes)} (limit {th.max_bytes}), compacted {len(compacted)} for "
        f"{len(exposure.fold(compacted, 3))} items (cap {th.cap}, 2.6 KB = {th.cap * 13}); "
        f"display-to-fold max {max(visible) * 1000:.1f} ms"
    )
    assert _p95(samples) <= BUDGET_MS
    assert max(sizes) <= th.max_bytes
    assert len(compacted) <= th.cap * exposure.RECORD_BYTES
    assert statistics.median(round_trips) == 2  # ledger + session vector (R4)
    assert max(visible) <= 1.0
