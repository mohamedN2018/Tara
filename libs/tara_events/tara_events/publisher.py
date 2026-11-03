"""Swappable event publisher.

Business code only ever calls ``get_publisher().publish(envelope)``. The
transport (RabbitMQ today via kombu; Kafka for the firehose later) is chosen by
settings, so changing it never touches a service's domain logic. See ADR-003.
"""

from __future__ import annotations

import json
from typing import Protocol

from django.conf import settings

from .envelope import EventEnvelope


class PublisherUnavailable(Exception):
    """The broker cannot be reached; says nothing about the event itself."""


class EventPublisher(Protocol):
    def publish(self, envelope: EventEnvelope) -> None: ...


class NullPublisher:
    """No-op publisher for tests / local runs without a broker."""

    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    def publish(self, envelope: EventEnvelope) -> None:
        self.published.append(envelope)


class KombuPublisher:
    """Publish to a RabbitMQ topic exchange; routing key = event_type.

    Connections are lazily created and reused, and rebuilt after a failure.
    Messages are persistent and broker-confirmed, so a row is only marked
    published once RabbitMQ has taken responsibility for it.
    """

    def __init__(self, broker_url: str, exchange_name: str) -> None:
        from kombu import Exchange

        self._broker_url = broker_url
        self._exchange = Exchange(exchange_name, type="topic", durable=True)
        self._connection = None
        self._producer = None

    def _ensure_producer(self):
        if self._producer is None:
            from kombu import Connection

            self._connection = Connection(
                self._broker_url,
                transport_options={"confirm_publish": True},
                connect_timeout=5,
            )
            self._producer = self._connection.Producer(serializer="json")
            self._exchange(self._connection).declare()
        return self._producer

    def _reset(self) -> None:
        connection, self._connection, self._producer = self._connection, None, None
        if connection is not None:
            try:
                connection.release()
            except Exception:  # noqa: BLE001, S110 - already broken
                pass

    def publish(self, envelope: EventEnvelope) -> None:
        from amqp.exceptions import ConnectionError as AMQPConnectionError
        from kombu.exceptions import OperationalError

        try:
            self._ensure_producer().publish(
                json.loads(json.dumps(envelope.to_dict())),
                exchange=self._exchange,
                routing_key=envelope.event_type,
                declare=[self._exchange],
                delivery_mode=2,  # persistent
                headers={
                    "event_id": envelope.event_id,
                    "event_type": envelope.event_type,
                    "event_version": envelope.event_version,
                    "partition_key": envelope.partition_key,
                },
            )
        except (OSError, OperationalError, AMQPConnectionError) as exc:
            self._reset()
            raise PublisherUnavailable(str(exc)) from exc


_publisher: EventPublisher | None = None


def get_publisher() -> EventPublisher:
    """Return the process-wide publisher chosen by settings.TARA_EVENT_PUBLISHER."""
    global _publisher
    if _publisher is not None:
        return _publisher

    backend = getattr(settings, "TARA_EVENT_PUBLISHER", "null")
    if backend == "rabbitmq":
        broker = settings.TARA_EVENT_BROKER_URL
        exchange = getattr(settings, "TARA_EVENT_EXCHANGE", "tara.events")
        _publisher = KombuPublisher(broker, exchange)
    else:
        _publisher = NullPublisher()
    return _publisher


def reset_publisher(publisher: EventPublisher | None = None) -> None:
    """Test hook to inject (or clear) the publisher."""
    global _publisher
    _publisher = publisher
