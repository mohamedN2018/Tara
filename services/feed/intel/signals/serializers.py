"""The ``POST /api/v1/feed/signals/`` contract (03 section 4.4).

The batch carries ``batch_id`` and ``session_id``; each event ``id``, ``t``,
``item`` (``<type>:<uuid>``), ``ts`` and, for items that came from a ranked
surface, ``st`` (the serve token). Attribution (surface, config version, variant,
source, position) is stamped by the server from the token: a ``cfg`` or
``variant`` field from the client is accepted and ignored, and any other unknown
field is refused. The JSON Schema is ``docs/intelligence/schemas/signals.batch.v1.json``.
"""

from __future__ import annotations

import uuid

from rest_framework import serializers

from ..models import CLIENT_EVENT_TYPES, SERVER_ONLY_EVENT_TYPES, EventType, ItemType
from . import validate

IGNORED_CLIENT_FIELDS = frozenset({"cfg", "variant"})
_BATCH_FIELDS = frozenset({"batch_id", "session_id", "events"})
_EVENT_FIELDS = frozenset(
    {
        "id",
        "t",
        "item",
        "ts",
        "st",
        "pos",
        "watch_ms",
        "pos_ms",
        "play_index",
        "surface",
        "idef",
        "dwell_ms",
    }
)


def _strip_ignored(data: dict, allowed: frozenset) -> dict:
    unknown = set(data) - allowed - IGNORED_CLIENT_FIELDS
    if unknown:
        raise serializers.ValidationError(
            {name: ["Unknown field."] for name in sorted(unknown)}, code="unknown_field"
        )
    return {k: v for k, v in data.items() if k not in IGNORED_CLIENT_FIELDS}


class SignalBatchSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField()
    session_id = serializers.UUIDField()
    events = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        max_length=validate.MAX_EVENTS_PER_BATCH,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({"non_field_errors": ["Expected an object."]})
        return super().to_internal_value(_strip_ignored(data, _BATCH_FIELDS))


class SignalEventSerializer(serializers.Serializer):
    """One client event. Invalid events are dropped one by one, never the batch."""

    id = serializers.UUIDField()
    t = serializers.CharField(max_length=24)
    item = serializers.CharField(max_length=48)
    ts = serializers.DateTimeField()
    st = serializers.CharField(max_length=512, required=False, allow_blank=True)
    pos = serializers.IntegerField(min_value=0, max_value=validate.MAX_POSITION, required=False)
    watch_ms = serializers.IntegerField(min_value=0, max_value=2**31 - 1, required=False)
    pos_ms = serializers.IntegerField(min_value=0, max_value=2**31 - 1, required=False)
    play_index = serializers.IntegerField(
        min_value=1, max_value=validate.MAX_PLAY_INDEX, required=False
    )
    surface = serializers.CharField(max_length=16, required=False, allow_blank=True)
    # ``feed_impression`` only: the impression rule the client measured with (WP
    # 4c.9-B3). Its range comes from the config (``validate.check_shape``).
    idef = serializers.IntegerField(required=False)
    # ``feed_dwell`` only (WP 4b.2): accumulated >= 50%-visible time of the card.
    dwell_ms = serializers.IntegerField(min_value=0, max_value=2**31 - 1, required=False)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({"non_field_errors": ["Expected an object."]})
        return super().to_internal_value(_strip_ignored(data, _EVENT_FIELDS))

    def validate_t(self, value: str) -> str:
        if value in SERVER_ONLY_EVENT_TYPES:
            raise serializers.ValidationError("Derived by the server.", code="server_only")
        if value not in CLIENT_EVENT_TYPES:
            raise serializers.ValidationError("Unknown event type.", code="unknown_type")
        return value

    def validate(self, attrs):
        kind, _, ident = attrs["item"].partition(":")
        if kind not in ItemType.values:
            raise serializers.ValidationError({"item": ["Unknown item type."]}, code="item")
        try:
            item_id = uuid.UUID(ident)
        except ValueError as exc:
            raise serializers.ValidationError({"item": ["Not an id."]}, code="item") from exc
        attrs["item_type"], attrs["item_id"] = kind, item_id
        if "idef" in attrs and attrs["t"] != EventType.FEED_IMPRESSION:
            # Like any field an event type does not define.
            raise serializers.ValidationError({"idef": ["Unknown field."]}, code="unknown_field")
        if "dwell_ms" in attrs and attrs["t"] != EventType.FEED_DWELL:
            raise serializers.ValidationError(
                {"dwell_ms": ["Unknown field."]}, code="unknown_field"
            )
        return attrs


def rejection_reason(errors: dict) -> str:
    """The metric label for an invalid event: its first error code."""
    for key in ("t", "item", "non_field_errors"):
        for err in errors.get(key, []):
            code = getattr(err, "code", None)
            if code in ("server_only", "unknown_type", "item", "unknown_field"):
                return code
    for value in errors.values():
        for err in value if isinstance(value, list) else [value]:
            if getattr(err, "code", None) == "unknown_field":
                return "unknown_field"
    return "invalid"
