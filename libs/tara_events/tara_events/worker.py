"""Kombu-based event-bus consumer.

Binds a durable queue to the topic exchange for every registered event type and
dispatches each message to its handler(s) under an idempotency guard. A failed
message waits in a delay queue and comes back, up to ``RETRY_DELAYS_SECONDS``
times. After that it is dead-lettered into this service's own DLQ (``<queue>.dlq``, bound to
``<exchange>.dlx`` with the queue's name; see ``topology``), and ``replay_dead_letters`` puts
it back.

Used by each service's ``consume_events`` management command. Kept transport-
specific to RabbitMQ here; the publisher side stays abstract (ADR-003).
"""

from __future__ import annotations

import logging

from amqp.exceptions import NotFound, PreconditionFailed
from django.db import close_old_connections
from kombu import Connection, Exchange, Producer, Queue, binding
from kombu.mixins import ConsumerMixin

from .dispatch import handlers_for, registered_event_types
from .envelope import EventEnvelope
from .topology import ORIGIN_HEADER, dlq_name, dlx_name, origin_queue

logger = logging.getLogger("tara.events.worker")

RETRY_DELAYS_SECONDS = (5, 30, 120, 600, 1800)
ATTEMPT_HEADER = "x-tara-attempt"


def _retry_queue_name(queue_name: str, delay: int) -> str:
    return f"{queue_name}.retry.{delay}s"


def declare_main_queue(connection, queue: Queue) -> bool:
    """Declare ``queue`` with its bindings; return ``True`` if the broker kept older arguments.

    A queue declared before 1.0c has ``x-dead-letter-exchange`` but no
    ``x-dead-letter-routing-key``, and RabbitMQ answers a redeclare with other arguments with
    406 PRECONDITION_FAILED (closing the channel). Then the queue is checked passively and only
    the bindings are (re)declared; the ``tara-dlq-<queue>`` policy supplies the routing key.
    """
    channel = connection.channel()
    try:
        queue(channel).declare()
        return False
    except PreconditionFailed:
        logger.warning(
            "queue %s keeps its pre-1.0c arguments; dead-letter routing comes from the "
            "policy (python -m tara_events.topology migrate)",
            queue.name,
        )
    finally:
        _close_quietly(channel)
    channel = connection.channel()
    try:
        bound = queue(channel)
        bound.queue_declare(passive=True)
        # Same steps as kombu's Queue.declare, minus the (failing) active queue declare.
        if bound.exchange and bound.exchange.name:
            bound.exchange.declare()
            bound.queue_bind()
        for b in bound.bindings:
            b.declare(channel)
            b.bind(bound, channel=channel)
    finally:
        _close_quietly(channel)
    return True


def _close_quietly(channel) -> None:
    try:
        channel.close()
    except Exception:  # noqa: S110 - a channel the broker closed after a 406 is already gone
        pass


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
        self.dlx = Exchange(dlx_name(exchange_name), type="topic", durable=True)
        # Only this service's dead letters: they carry the queue's name as routing key.
        self.dlq = Queue(
            dlq_name(queue_name), exchange=self.dlx, routing_key=queue_name, durable=True
        )
        self.legacy_queue_arguments = False

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
            queue_arguments={
                "x-dead-letter-exchange": self.dlx.name,
                "x-dead-letter-routing-key": queue_name,
            },
        )

    def get_consumers(self, Consumer, channel):  # noqa: N803 - kombu signature
        # Ensure the dead-letter topology exists before consuming.
        self.dlx(channel).declare()
        self.dlq(channel).declare()
        for queue in self.retry_queues:
            queue(channel).declare()
        # Side channels on the consuming connection: a 406 closes the channel it happens on.
        self.legacy_queue_arguments = declare_main_queue(channel.connection, self.queue)
        self.producer = Producer(channel)
        return [
            Consumer(
                # Declared above (tolerating pre-1.0c arguments), so kombu must not redeclare.
                queues=[Queue(self.queue.name, no_declare=True)],
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


def should_replay(headers: dict | None, queue_name: str) -> bool:
    """A dead letter belongs to this queue unless its ``x-death`` names another one.

    Before 1.0c every DLQ also got every other service's dead letters (shared ``#`` binding);
    those copies are left in place for ``topology migrate`` instead of being replayed here.
    """
    origin = origin_queue(headers)
    return origin is None or origin == queue_name


def replay_dead_letters(*, broker_url: str, queue_name: str) -> int:
    """Move this queue's messages in ``<queue_name>.dlq`` back to it, with fresh retries."""
    moved = skipped = 0
    with Connection(broker_url) as conn:
        channel = conn.channel()
        try:
            # Passive: never declare (or bind) anything here.
            channel.queue_declare(dlq_name(queue_name), passive=True)
        except NotFound:
            return 0
        dlq = Queue(dlq_name(queue_name), no_declare=True)(channel)
        producer = conn.Producer()
        while True:
            message = dlq.get(no_ack=False)
            if message is None:
                break
            if not should_replay(message.headers, queue_name):
                skipped += 1  # left unacked: requeued when the channel closes
                continue
            headers = {k: v for k, v in (message.headers or {}).items() if k != ATTEMPT_HEADER}
            headers.pop("x-death", None)
            headers.pop(ORIGIN_HEADER, None)
            producer.publish(
                message.payload,
                exchange="",
                routing_key=queue_name,
                delivery_mode=2,
                headers=headers,
            )
            message.ack()
            moved += 1
        channel.close()
    if skipped:
        logger.warning("left %d dead letters of other queues in %s", skipped, dlq_name(queue_name))
    return moved
