"""Event consumers: map domain events to in-app notifications.

Each handler runs under the consumer's idempotency guard, so re-delivery does not
create duplicate notifications.
"""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

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
    )


@on_event("post.commented")
def on_post_commented(e: EventEnvelope) -> None:
    p = e.payload
    notify(
        p["post_author_id"],
        "post.comment",
        actor_id=p.get("author"),
        subject_ref=f"post:{p['post_id']}",
        body="commented on your post",
    )


@on_event("comment.replied")
def on_comment_replied(e: EventEnvelope) -> None:
    p = e.payload
    notify(
        p["post_author_id"],
        "comment.reply",
        actor_id=p.get("author"),
        subject_ref=f"post:{p['post_id']}",
        body="replied to a comment",
    )


@on_event("friendship.requested")
def on_friend_requested(e: EventEnvelope) -> None:
    p = e.payload
    notify(p["to"], "friend.request", actor_id=p.get("from"), body="sent you a friend request")


@on_event("friendship.accepted")
def on_friend_accepted(e: EventEnvelope) -> None:
    p = e.payload
    for member in (p.get("a"), p.get("b")):
        notify(member, "friend.accepted", actor_id=e.actor_id, body="accepted your friend request")


@on_event("user.followed")
def on_user_followed(e: EventEnvelope) -> None:
    p = e.payload
    if p.get("target_type", "user") == "user":
        notify(p["target"], "follow", actor_id=p.get("follower"), body="started following you")


@on_event("message.created")
def on_message_created(e: EventEnvelope) -> None:
    p = e.payload
    sender = p.get("sender")
    for recipient in p.get("recipients", []):
        if str(recipient) != str(sender):
            notify(
                recipient,
                "message",
                actor_id=sender,
                subject_ref=f"conversation:{p['conversation_id']}",
                group_key=str(p["conversation_id"]),
                body=p.get("preview", "sent a message"),
            )


@on_event("listing.status.changed")
def on_listing_status(e: EventEnvelope) -> None:
    p = e.payload
    notify(
        p["seller_id"],
        "listing.status",
        subject_ref=f"listing:{p['listing_id']}",
        body=f"your listing is now {p.get('to')}",
    )
