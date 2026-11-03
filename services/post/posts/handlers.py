"""Event consumers for the Post service."""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services
from .models import BlockedPair


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.get_or_create(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"])


@on_event("user.unblocked")
def on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()


@on_event("moderation.actioned")
def on_moderation_actioned(event: EventEnvelope) -> None:
    p = event.payload
    if p.get("target_type") == "post":
        services.apply_moderation(p["target_id"], p.get("action", ""))


@on_event("post.created")
def on_post_created_preview(event: EventEnvelope) -> None:
    services.refresh_link_preview(event.payload["post_id"])


@on_event("post.updated")
def on_post_updated_preview(event: EventEnvelope) -> None:
    services.refresh_link_preview(event.payload["post_id"])


@on_event("post.created")
def on_post_created_mentions(event: EventEnvelope) -> None:
    p = event.payload
    services.notify_mentions(
        actor_id=p["author_id"], post_id=p["post_id"], handles=p.get("mentions", [])
    )


@on_event("post.updated")
def on_post_updated_mentions(event: EventEnvelope) -> None:
    p = event.payload
    services.notify_mentions(
        actor_id=p["author_id"], post_id=p["post_id"], handles=p.get("new_mentions", [])
    )


@on_event("post.commented")
@on_event("comment.replied")
def on_comment_mentions(event: EventEnvelope) -> None:
    p = event.payload
    services.notify_mentions(
        actor_id=p["author"],
        post_id=p["post_id"],
        handles=p.get("mentions", []),
        comment_id=p.get("comment_id"),
    )
