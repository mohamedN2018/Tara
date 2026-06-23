"""Event consumers for the Feed service."""

from __future__ import annotations

import logging

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services

logger = logging.getLogger("tara.feed.handlers")


@on_event("post.created")
def on_post_created(event: EventEnvelope) -> None:
    """Fan the new post out to recipient feeds (raises -> retried if Graph down)."""
    count = services.fan_out_post(event.payload)
    logger.info(
        "fanned out post", extra={"post_id": event.payload.get("post_id"), "recipients": count}
    )


@on_event("user.unfollowed")
def on_user_unfollowed(event: EventEnvelope) -> None:
    p = event.payload
    if p.get("target_type", "user") == "user":
        services.remove_author_from_recipient(p["follower"], p["target"])


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    # Remove each party's posts from the other's feed.
    services.remove_author_from_recipient(p["blocker_id"], p["blocked_id"])
    services.remove_author_from_recipient(p["blocked_id"], p["blocker_id"])
