"""Tara event backbone.

Provides the versioned event envelope, the outbox abstract models (each service
defines a concrete table it owns), a swappable publisher (RabbitMQ today, Kafka
for the firehose later), and the relay that drains the outbox.

See docs/architecture/phase-0/04-event-contracts.md.
"""

from .dispatch import on_event, registered_event_types
from .envelope import EventEnvelope, uuid7

__all__ = ["EventEnvelope", "on_event", "registered_event_types", "uuid7", "__version__"]
__version__ = "0.1.0"
