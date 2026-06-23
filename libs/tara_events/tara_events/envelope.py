"""Versioned, immutable event envelope + UUIDv7 helper.

Envelope shape is fixed in docs/architecture/phase-0/04-event-contracts.md §1.
UUIDv7 gives globally-unique, time-sortable ids (good index locality, safe
across services) — the stdlib has no uuid7 in 3.12, so we implement RFC 9562.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def uuid7() -> uuid.UUID:
    """Generate a UUIDv7 (48-bit ms timestamp + random) per RFC 9562."""
    unix_ms = int(time.time() * 1000)
    rand = os.urandom(10)  # 80 random bits
    # 48 bits timestamp
    ts = unix_ms.to_bytes(6, "big")
    # rand_a (12 bits) goes in bytes 6-7 with version nibble
    rand_a = int.from_bytes(rand[0:2], "big") & 0x0FFF
    b6_7 = (0x7 << 12) | rand_a  # version 7
    # variant (10) in top bits of byte 8
    rand_b_hi = (0b10 << 6) | (rand[2] & 0x3F)
    value = ts + b6_7.to_bytes(2, "big") + bytes([rand_b_hi]) + rand[3:10]
    return uuid.UUID(bytes=value)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class EventEnvelope:
    """One immutable domain fact."""

    event_type: str
    payload: dict[str, Any]
    subject_id: str
    producer: str
    event_version: int = 1
    actor_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    partition_key: str | None = None
    event_id: str = field(default_factory=lambda: str(uuid7()))
    occurred_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        # partition_key defaults to the subject so per-entity ordering holds.
        if self.partition_key is None:
            object.__setattr__(self, "partition_key", self.subject_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "occurred_at": self.occurred_at,
            "producer": self.producer,
            "actor_id": self.actor_id,
            "subject_id": self.subject_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "partition_key": self.partition_key,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EventEnvelope:
        return cls(
            event_id=raw["event_id"],
            event_type=raw["event_type"],
            event_version=raw.get("event_version", 1),
            occurred_at=raw.get("occurred_at", _utc_now_iso()),
            producer=raw.get("producer", "unknown"),
            actor_id=raw.get("actor_id"),
            subject_id=raw["subject_id"],
            correlation_id=raw.get("correlation_id"),
            causation_id=raw.get("causation_id"),
            partition_key=raw.get("partition_key"),
            payload=raw.get("payload", {}),
        )
