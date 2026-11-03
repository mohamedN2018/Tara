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
        # Only items the follow brought in: a friend who unfollows keeps friend items.
        services.remove_follow_items(p["follower"], p["target"])


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    # Remove each party's posts from the other's feed.
    services.remove_author_from_recipient(p["blocker_id"], p["blocked_id"])
    services.remove_author_from_recipient(p["blocked_id"], p["blocker_id"])


@on_event("post.deleted")
def on_post_deleted(event: EventEnvelope) -> None:
    services.remove_post(event.payload["post_id"], services.occurred_at(event.occurred_at))


@on_event("post.updated")
def on_post_updated(event: EventEnvelope) -> None:
    """Narrowing the audience drops the rows it no longer reaches (no Graph call)."""
    p = event.payload
    services.update_post_excerpt(
        p["post_id"],
        p.get("excerpt", ""),
        p.get("audience"),
        p.get("media_ids"),
        when=services.occurred_at(event.occurred_at),
    )


@on_event("friendship.removed")
def on_friendship_removed(event: EventEnvelope) -> None:
    p = event.payload
    services.apply_unfriend(p["a"], p["b"])


@on_event("friendship.accepted")
def on_friendship_accepted(event: EventEnvelope) -> None:
    """Relabel `follow` items between new friends (raises -> retried if Graph down)."""
    p = event.payload
    services.label_friend_items(p["a"], p["b"])
