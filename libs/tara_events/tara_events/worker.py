"""Kombu-based event-bus consumer.

Binds a durable queue to the topic exchange for every registered event type and
dispatches each message to its handler(s) under an idempotency guard. A failed
message waits in a delay queue and comes back, up to ``RETRY_DELAYS_SECONDS``
times. After that it is dead-lettered, and ``replay_dead_letters`` puts it back.

Used by each service's ``consume_events`` management command. Kept transport-
specific to RabbitMQ here; the publisher side stays abstract (ADR-003).
"""

from __future__ import annotations

import logging

from django.db import close_old_connections
from kombu import Connection, Exchange, Producer, Queue, binding
from kombu.mixins import ConsumerMixin

from .dispatch import handlers_for, registered_event_types
from .envelope import EventEnvelope

logger = logging.getLogger("tara.events.worker")

RETRY_DELAYS_SECONDS = (5, 30, 120, 600, 1800)
ATTEMPT_HEADER = "x-tara-attempt"


def _retry_queue_name(queue_name: str, delay: int) -> str:
    return f"{queue_name}.retry.{delay}s"


class EventWorker(ConsumerMixin):
    def __init__(
        self,
        connection: Connection,
        *,
        exchange_name: str,
        queue_name: str,
        processed_model=None,
        consumer_name: str = "default",
        prefetch: int = 20,
    ) -> None:
        self.connection = connection
        self.consumer_name = consumer_name
        self.processed_model = processed_model
        self.prefetch = prefetch

        self.exchange = Exchange(exchange_name, type="topic", durable=True)
        self.dlx = Exchange(f"{exchange_name}.dlx", type="topic", durable=True)
        self.dlq = Queue(f"{queue_name}.dlq", exchange=self.dlx, routing_key="#", durable=True)

        bindings = [binding(self.exchange, routing_key=rk) for rk in registered_event_types()]
        self.queue_name = queue_name
        # An expired message goes back to the main queue through the default exchange.
        self.retry_queues = [
            Queue(
                _retry_queue_name(queue_name, delay),
                durable=True,
                queue_arguments={
                    "x-message-ttl": delay * 1000,
                    "x-dead-letter-exchange": "",
                    "x-dead-letter-routing-key": queue_name,
                },
            )
            for delay in RETRY_DELAYS_SECONDS
        ]
        self.queue = Queue(
            queue_name,
            exchange=self.exchange,
            bindings=bindings,
            durable=True,
            queue_arguments={"x-dead-letter-exchange": self.dlx.name},
        )

    def get_consumers(self, Consumer, channel):  # noqa: N803 - kombu signature
        # Ensure the dead-letter topology exists before consuming.
        self.dlx(channel).declare()
        self.dlq(channel).declare()
        for queue in self.retry_queues:
            queue(channel).declare()
        self.producer = Producer(channel)
        return [
            Consumer(
                queues=[self.queue],
                callbacks=[self.on_message],
                accept=["json"],
                prefetch_count=self.prefetch,
            )
        ]

    def on_message(self, body, message) -> None:
        try:
            envelope = EventEnvelope.from_dict(body)
        except Exception:
            logger.exception("malformed event; dead-lettering")
            message.reject(requeue=False)
            return

        close_old_connections()
        try:
            self._dispatch(envelope)
        except Exception:
            logger.exception("handler failed for event %s", body.get("event_id"))
            self._retry_or_dead_letter(body, message)
            return
        finally:
            close_old_connections()
        message.ack()

    def _retry_or_dead_letter(self, body, message) -> None:
        attempt = int((message.headers or {}).get(ATTEMPT_HEADER, 0))
        if attempt >= len(RETRY_DELAYS_SECONDS):
            message.reject(requeue=False)  # -> DLX/DLQ for inspection + replay
            return
        self.producer.publish(
            body,
            exchange="",
            routing_key=_retry_queue_name(self.queue_name, RETRY_DELAYS_SECONDS[attempt]),
            delivery_mode=2,
            headers={**(message.headers or {}), ATTEMPT_HEADER: attempt + 1},
        )
        message.ack()

    def _dispatch(self, envelope: EventEnvelope) -> None:
        handlers = handlers_for(envelope.event_type)
        if not handlers:
            return
        for fn in handlers:
            if self.processed_model is not None:
                from .consumer import idempotent

                with idempotent(
                    self.processed_model, envelope.event_id, f"{self.consumer_name}:{fn.__name__}"
                ) as fresh:
                    if fresh:
                        fn(envelope)
            else:
                fn(envelope)


def run_worker(
    *,
    broker_url: str,
    exchange_name: str,
    queue_name: str,
    processed_model=None,
    consumer_name="default",
) -> None:
    """Blocking entrypoint used by the `consume_events` management command."""
    logger.info("event worker starting", extra={"queue": queue_name, "consumer": consumer_name})
    with Connection(broker_url, heartbeat=30) as conn:
        EventWorker(
            conn,
            exchange_name=exchange_name,
            queue_name=queue_name,
            processed_model=processed_model,
            consumer_name=consumer_name,
        ).run()


def replay_dead_letters(*, broker_url: str, queue_name: str) -> int:
    """Move everything in ``<queue_name>.dlq`` back to the main queue, with fresh retries."""
    moved = 0
    with Connection(broker_url) as conn:
        dlq = conn.SimpleQueue(f"{queue_name}.dlq", no_ack=False)
        # Passive: never redeclare a queue with different arguments.
        producer = conn.Producer()
        while True:
            try:
                message = dlq.get(block=False)
            except dlq.Empty:
                break
            headers = {k: v for k, v in (message.headers or {}).items() if k != ATTEMPT_HEADER}
            headers.pop("x-death", None)
            producer.publish(
                message.payload,
                exchange="",
                routing_key=queue_name,
                delivery_mode=2,
                headers=headers,
            )
            message.ack()
            moved += 1
        dlq.close()
    return moved
