"""Event consumers for the Feed service."""

from __future__ import annotations

import logging

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import readmodels, services
from .models import RelationshipFlag

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
    target_type = p.get("target_type", "user")
    readmodels.set_follow(
        p["follower"], p["target"], target_type, False, services.occurred_at(event.occurred_at)
    )
    if target_type == "user":
        # Only items the follow brought in: a friend who unfollows keeps friend items.
        services.remove_follow_items(p["follower"], p["target"])


@on_event("user.followed")
def on_user_followed(event: EventEnvelope) -> None:
    """The ``following`` mode's edge (rows labelled ``follow`` count too)."""
    p = event.payload
    readmodels.set_follow(
        p["follower"],
        p["target"],
        p.get("target_type", "user"),
        True,
        services.occurred_at(event.occurred_at),
    )


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    # Remove each party's posts from the other's feed.
    services.remove_author_from_recipient(p["blocker_id"], p["blocked_id"])
    services.remove_author_from_recipient(p["blocked_id"], p["blocker_id"])
    readmodels.forget_pair(p["blocker_id"], p["blocked_id"])


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


# ---- 2A: Graph's mutes and favorites (consumers ship before graph emits) -------


def _relationship(event: EventEnvelope, kind: str, active: bool) -> None:
    p = event.payload
    when = services.occurred_at(p.get("occurred_at") or event.occurred_at)
    readmodels.set_flag(p["actor_id"], p["target_id"], kind, active, when)


@on_event("relationship.muted")
def on_relationship_muted(event: EventEnvelope) -> None:
    """A muted author leaves the muter's feed in every mode (rows stay: unmute restores)."""
    _relationship(event, RelationshipFlag.Kind.MUTE, True)


@on_event("relationship.unmuted")
def on_relationship_unmuted(event: EventEnvelope) -> None:
    _relationship(event, RelationshipFlag.Kind.MUTE, False)


@on_event("relationship.favorited")
def on_relationship_favorited(event: EventEnvelope) -> None:
    """The ``favorites`` mode, and a boost in ``for_you``."""
    _relationship(event, RelationshipFlag.Kind.FAVORITE, True)


@on_event("relationship.unfavorited")
def on_relationship_unfavorited(event: EventEnvelope) -> None:
    _relationship(event, RelationshipFlag.Kind.FAVORITE, False)


# ---- 1.7: engagement and affinity for the ranking -------------------------------


def _reaction(event: EventEnvelope, active: bool) -> None:
    p = event.payload
    readmodels.set_reaction(
        p["post_id"],
        p.get("reactor"),
        p.get("author_id"),
        active,
        services.occurred_at(event.occurred_at),
    )


@on_event("post.reacted")
def on_post_reacted(event: EventEnvelope) -> None:
    """Newest event per (post, reactor) wins: a late, retried react changes nothing."""
    _reaction(event, True)


@on_event("post.unreacted")
def on_post_unreacted(event: EventEnvelope) -> None:
    _reaction(event, False)


def _comment_created(event: EventEnvelope) -> None:
    p = event.payload
    readmodels.set_comments(
        p["post_id"],
        [p.get("comment_id")],
        True,
        services.occurred_at(event.occurred_at),
        author_id=p.get("author"),
        post_author_id=p.get("post_author_id"),
    )


@on_event("post.commented")
def on_post_commented(event: EventEnvelope) -> None:
    _comment_created(event)


@on_event("comment.replied")
def on_comment_replied(event: EventEnvelope) -> None:
    _comment_created(event)


@on_event("comment.deleted")
def on_comment_deleted(event: EventEnvelope) -> None:
    """A deleted comment (a root takes its replies) stops counting for the post."""
    p = event.payload
    readmodels.set_comments(
        p["post_id"],
        p.get("removed_ids") or [p.get("comment_id")],
        False,
        services.occurred_at(event.occurred_at),
        author_id=p.get("author_id"),
        post_author_id=p.get("post_author_id"),
    )


@on_event("comment.restored")
def on_comment_restored(event: EventEnvelope) -> None:
    """An overturned moderation removal counts the comments it brings back again."""
    p = event.payload
    readmodels.set_comments(
        p["post_id"],
        p.get("restored_ids") or [p.get("comment_id")],
        True,
        services.occurred_at(event.occurred_at),
    )


@on_event("post.shared")
def on_post_shared(event: EventEnvelope) -> None:
    p = event.payload
    readmodels.bump_stats(p["post_id"], shares=1)
    readmodels.bump_affinity(p.get("sharer"), p.get("author_id"), 1)


@on_event("profile.updated")
def on_profile_updated(event: EventEnvelope) -> None:
    """``searchable`` (1.6) arrives here; an event without it changes nothing."""
    if "searchable" not in event.payload:
        return
    readmodels.set_searchable(
        event.subject_id,
        bool(event.payload["searchable"]),
        services.occurred_at(event.occurred_at),
    )
