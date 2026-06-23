"""Kombu-based event-bus consumer.

Binds a durable queue to the topic exchange for every registered event type,
dispatches each message to its handler(s) under an idempotency guard, and
dead-letters anything that fails (after which it can be inspected/replayed).

Used by each service's ``consume_events`` management command. Kept transport-
specific to RabbitMQ here; the publisher side stays abstract (ADR-003).
"""

from __future__ import annotations

import logging

from kombu import Connection, Exchange, Queue, binding
from kombu.mixins import ConsumerMixin

from .dispatch import handlers_for, registered_event_types
from .envelope import EventEnvelope

logger = logging.getLogger("tara.events.worker")


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

        try:
            self._dispatch(envelope)
        except Exception:
            logger.exception("handler failed for event %s; dead-lettering", body.get("event_id"))
            message.reject(requeue=False)  # -> DLX/DLQ for inspection + replay
            return
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
