"""WP 2.0: measured outbox relay throughput (replaces the "about 100 events/s" estimate).

Not collected by default (``bench_*``). Writes 10,000 synthetic outbox rows in the
*test* database and drains them with ``tara_events.outbox.publish_pending`` (batches
of 200, one ``UPDATE`` per row), once with the null publisher (database cost only)
and once with the real RabbitMQ publisher when ``BENCH_RABBITMQ_URL`` is set. The
routing key ``intel.bench.synthetic`` has no binding, so no consumer receives them.

    BENCH_RABBITMQ_URL=amqp://... python -m pytest -q -s intel/tests/bench_outbox_relay.py
"""

import os
import time

import pytest
from feed.models import OutboxEvent

from tara_events.envelope import EventEnvelope
from tara_events.outbox import publish_pending
from tara_events.publisher import KombuPublisher, NullPublisher

pytestmark = pytest.mark.django_db(transaction=True)
ROWS = 10_000


def _fill():
    OutboxEvent.objects.all().delete()
    rows = []
    for i in range(ROWS):
        env = EventEnvelope(
            event_type="intel.bench.synthetic",
            subject_id=str(i),
            producer="feed-bench",
            payload={"n": i, "data_origin": "synthetic"},
        )
        rows.append(
            OutboxEvent(
                id=env.event_id,
                event_type=env.event_type,
                payload=env.to_dict(),
                partition_key=env.partition_key,
            )
        )
    OutboxEvent.objects.bulk_create(rows, batch_size=2000)


def _drain(publisher) -> float:
    start = time.perf_counter()
    published = 0
    while True:
        n = publish_pending(OutboxEvent, publisher=publisher, batch_size=200)
        if not n:
            break
        published += n
    seconds = time.perf_counter() - start
    assert published == ROWS
    return ROWS / seconds


def test_relay_throughput():
    _fill()
    null_rate = _drain(NullPublisher())
    print(f"\nrelay, null publisher (database only): {null_rate:.0f} events/s")
    url = os.getenv("BENCH_RABBITMQ_URL")
    if url:
        _fill()
        publisher = KombuPublisher(url, os.getenv("TARA_EVENT_EXCHANGE", "tara.events"))
        rabbit_rate = _drain(publisher)
        print(f"relay, RabbitMQ publisher: {rabbit_rate:.0f} events/s")
    OutboxEvent.objects.all().delete()
