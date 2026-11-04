"""Event consumers for the Post service."""

from __future__ import annotations

from django.db import transaction

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import composer, groups, services
from .models import BlockedPair


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    """A block is respected both ways on tags too: neither keeps a tag of the
    other on their posts (2C). Idempotent, one transaction."""
    p = event.payload
    with transaction.atomic():
        BlockedPair.objects.get_or_create(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"])
        composer.drop_tags_between(p["blocker_id"], p["blocked_id"])


@on_event("user.unblocked")
def on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()


@on_event("moderation.actioned")
def on_moderation_actioned(event: EventEnvelope) -> None:
    p = event.payload
    if p.get("target_type") == "post":
        services.apply_moderation(p["target_id"], p.get("action", ""))
    elif p.get("target_type") == "comment":
        services.apply_comment_moderation(p["target_id"], p.get("action", ""))
    elif p.get("target_type") == "gathering":
        from gatherings.services import apply_moderation as apply_gathering_moderation

        apply_gathering_moderation(p["target_id"], p.get("action", ""))


@on_event("post.deleted")  # also emitted when moderation removes a post
def on_post_deleted_restrict_media(event: EventEnvelope) -> None:
    """Outside the delete's transaction, and retried while media is down."""
    services.restrict_media_of_hidden_post(event.payload["post_id"])


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


@on_event("post.created")
def on_post_created_tags(event: EventEnvelope) -> None:
    """People tagged in a post hear about it once it is published (2C)."""
    p = event.payload
    composer.notify_tags(
        actor_id=p["author_id"], post_id=p["post_id"], account_ids=p.get("tagged_ids") or []
    )


@on_event("post.approved")
def on_post_approved_tags(event: EventEnvelope) -> None:
    """A group post held for approval tells its tagged people when it goes out."""
    p = event.payload
    composer.notify_tags(
        actor_id=p["author_id"], post_id=p["post_id"], account_ids=p.get("tagged_ids") or []
    )


@on_event("post.updated")
def on_post_updated_tags(event: EventEnvelope) -> None:
    p = event.payload
    composer.notify_tags(
        actor_id=p["author_id"], post_id=p["post_id"], account_ids=p.get("new_tagged_ids") or []
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


@on_event("comment.edited")
def on_comment_edited_mentions(event: EventEnvelope) -> None:
    p = event.payload
    services.notify_mentions(
        actor_id=p["author"],
        post_id=p["post_id"],
        handles=p.get("new_mentions", []),
        comment_id=p.get("comment_id"),
    )


# ---- group read model (profile's group.* events, roadmap 1.11) ----------------------


@on_event("group.created")
@on_event("group.updated")
@on_event("group.deleted")  # also a moderator's removal (status "suspended")
def on_group_changed(event: EventEnvelope) -> None:
    payload = dict(event.payload)
    if event.event_type == "group.deleted" and payload.get("status") == "active":
        payload["status"] = "deleted"  # an older producer without a status
    groups.apply_group_event(payload, event.occurred_at)


@on_event("group.member.changed")
def on_group_member_changed(event: EventEnvelope) -> None:
    groups.apply_member_event(event.payload, event.occurred_at)
