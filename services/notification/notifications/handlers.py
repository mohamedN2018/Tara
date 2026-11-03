"""Event consumers: map domain events to notifications, and clean them up.

Each handler runs under the consumer's idempotency guard, so re-delivery does not
create duplicate notifications. Aggregated kinds (see ``registry``) count each
distinct actor once, so a redelivered or repeated event never inflates a count.
"""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services
from .services import notify


@on_event("post.reacted")
def on_post_reacted(e: EventEnvelope) -> None:
    p = e.payload
    notify(
        p["author_id"],
        "post.reaction",
        actor_id=p.get("reactor"),
        subject_ref=f"post:{p['post_id']}",
        body="reacted to your post",
        data={"post_id": p["post_id"], "reaction_type": p.get("reaction_type")},
    )


@on_event("post.commented")
def on_post_commented(e: EventEnvelope) -> None:
    p = e.payload
    comment_id = p.get("comment_id")
    notify(
        p["post_author_id"],
        "post.comment",
        actor_id=p.get("author"),
        subject_ref=f"post:{p['post_id']}",
        target_ref=f"comment:{comment_id}" if comment_id else "",
        body="commented on your post",
        data={"post_id": p["post_id"], "comment_id": comment_id},
    )


@on_event("comment.replied")
def on_comment_replied(e: EventEnvelope) -> None:
    p = e.payload
    comment_id = p.get("comment_id")
    notify(
        p.get("parent_author_id") or p["post_author_id"],  # older events lack the parent author
        "comment.reply",
        actor_id=p.get("author"),
        subject_ref=f"post:{p['post_id']}",
        target_ref=f"comment:{comment_id}" if comment_id else "",
        body="replied to your comment",
        data={"post_id": p["post_id"], "comment_id": comment_id, "parent_id": p.get("parent_id")},
    )


@on_event("user.mentioned")
def on_user_mentioned(e: EventEnvelope) -> None:
    p = e.payload
    comment_id = p.get("comment_id")
    notify(
        p["recipient"],
        "mention",
        actor_id=p.get("actor"),
        subject_ref=f"post:{p['post_id']}",
        target_ref=f"comment:{comment_id}" if comment_id else "",
        body="mentioned you",
        data={"post_id": p["post_id"], "comment_id": comment_id},
    )


@on_event("post.shared")
def on_post_shared(e: EventEnvelope) -> None:
    p = e.payload
    if p.get("author_id"):
        # Grouped per original post; one sharer links to their share instead.
        notify(
            p["author_id"],
            "post.share",
            actor_id=p.get("sharer"),
            subject_ref=f"post:{p['post_id']}",
            body="shared your post",
            data={"post_id": p["post_id"], "share_post_id": p.get("share_post_id")},
        )


@on_event("post.deleted")
def on_post_deleted(e: EventEnvelope) -> None:
    post_id = e.payload.get("post_id") or e.subject_id
    if post_id:
        services.purge_subject(f"post:{post_id}")


@on_event("friendship.requested")
def on_friend_requested(e: EventEnvelope) -> None:
    p = e.payload
    sender = p.get("from")
    notify(
        p["to"],
        "friend.request",
        actor_id=sender,
        subject_ref=f"account:{sender}" if sender else "",
        body="sent you a friend request",
        data={"request_id": e.subject_id},
    )


@on_event("friendship.accepted")
def on_friend_accepted(e: EventEnvelope) -> None:
    p = e.payload
    # The request notification in the accepter's list now shows "accepted",
    # whichever device or screen accepted it.
    services.resolve_friend_request(e.subject_id, "accepted")
    for member in (p.get("a"), p.get("b")):
        notify(
            member,
            "friend.accepted",
            actor_id=e.actor_id,
            subject_ref=f"account:{e.actor_id}" if e.actor_id else "",
            body="accepted your friend request",
        )


@on_event("friendship.request.withdrawn")
def on_friend_request_withdrawn(e: EventEnvelope) -> None:
    """Consumer ships first; graph emits it in a later release (roadmap 2.18)."""
    services.resolve_friend_request(e.subject_id, "withdrawn")


@on_event("user.followed")
def on_user_followed(e: EventEnvelope) -> None:
    p = e.payload
    if p.get("target_type", "user") == "user":
        follower = p.get("follower")
        notify(
            p["target"],
            "follow",
            actor_id=follower,
            subject_ref=f"account:{follower}" if follower else "",
            body="started following you",
        )


@on_event("user.blocked")
def on_user_blocked(e: EventEnvelope) -> None:
    p = e.payload
    blocker, blocked = p.get("blocker_id"), p.get("blocked_id")
    if blocker and blocked:
        services.remove_actor(blocker, blocked)
        services.remove_actor(blocked, blocker)


@on_event("message.created")
def on_message_created(e: EventEnvelope) -> None:
    p = e.payload
    sender = p.get("sender")
    muted = {str(m) for m in p.get("muted", [])}
    conversation_id = p["conversation_id"]
    for recipient in p.get("recipients", []):
        if str(recipient) != str(sender) and str(recipient) not in muted:
            notify(
                recipient,
                "message",
                actor_id=sender,
                subject_ref=f"conversation:{conversation_id}",
                group_key=str(conversation_id),
                # Attachment-only messages have no text; the client words those.
                body=p.get("preview") or "",
                data={"conversation_id": conversation_id, "message_type": p.get("type")},
            )


@on_event("message.read")
def on_message_read(e: EventEnvelope) -> None:
    p = e.payload
    if p.get("reader") and p.get("conversation_id"):
        services.clear_conversation(p["reader"], p["conversation_id"])


@on_event("listing.status.changed")
def on_listing_status(e: EventEnvelope) -> None:
    p = e.payload
    # The seller's own change is not news to them. Other actors (moderators)
    # are not named, so actor_id is left empty.
    if e.actor_id and str(e.actor_id) == str(p.get("seller_id")):
        return
    notify(
        p["seller_id"],
        "listing.status",
        subject_ref=f"listing:{p['listing_id']}",
        body=f"your listing is now {p.get('to')}",
        data={"listing_id": p["listing_id"], "status": p.get("to")},
    )
