"""Validate outbox payloads against the JSON Schemas in ``libs/tara_events``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from posts.models import OutboxEvent

SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")


def rows(event_type: str) -> list[OutboxEvent]:
    return list(OutboxEvent.objects.filter(event_type=event_type).order_by("created_at", "id"))


def payloads(event_type: str) -> list[dict]:
    return [r.payload["payload"] for r in rows(event_type)]


def assert_valid(event_type: str, payload: dict) -> None:
    """Fail when the payload breaks its schema (``FormatChecker`` checks uuids and dates)."""
    if not SCHEMAS.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    import jsonschema

    schema = json.loads((SCHEMAS / f"{event_type}.v1.json").read_text())
    jsonschema.validate(payload, schema, format_checker=jsonschema.FormatChecker())


def assert_all_valid(event_type: str) -> int:
    found = payloads(event_type)
    for payload in found:
        assert_valid(event_type, payload)
    return len(found)
