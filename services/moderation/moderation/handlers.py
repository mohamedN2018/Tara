"""Event consumers: turn `*.reported` events into moderation cases."""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services


@on_event("post.reported")
def on_post_reported(e: EventEnvelope) -> None:
    services.ingest_report_event("post.reported", e.payload)


@on_event("comment.reported")
def on_comment_reported(e: EventEnvelope) -> None:
    services.ingest_report_event("comment.reported", e.payload)


@on_event("listing.reported")
def on_listing_reported(e: EventEnvelope) -> None:
    services.ingest_report_event("listing.reported", e.payload)


@on_event("marketplace.review.reported")
def on_listing_review_reported(e: EventEnvelope) -> None:
    services.ingest_report_event("marketplace.review.reported", e.payload)


@on_event("message.reported")
def on_message_reported(e: EventEnvelope) -> None:
    services.ingest_report_event("message.reported", e.payload)


@on_event("gathering.reported")
def on_gathering_reported(e: EventEnvelope) -> None:
    services.ingest_report_event("gathering.reported", e.payload)


@on_event("group.reported")
def on_group_reported(e: EventEnvelope) -> None:
    services.ingest_report_event("group.reported", e.payload)


@on_event("story.reported")
def on_story_reported(e: EventEnvelope) -> None:
    services.ingest_report_event("story.reported", e.payload)


@on_event("intel.integrity.flagged")
def on_integrity_flagged(e: EventEnvelope) -> None:
    """Feed's spam / sexual hide signal (WP 7.4): a system-sourced report."""
    services.ingest_system_flag(e.payload)
