"""Event consumers: turn `*.reported` events into moderation cases."""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services


@on_event("post.reported")
def on_post_reported(e: EventEnvelope) -> None:
    services.ingest_report_event("post.reported", e.payload)


@on_event("listing.reported")
def on_listing_reported(e: EventEnvelope) -> None:
    services.ingest_report_event("listing.reported", e.payload)


@on_event("message.reported")
def on_message_reported(e: EventEnvelope) -> None:
    services.ingest_report_event("message.reported", e.payload)
