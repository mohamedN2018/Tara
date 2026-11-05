"""Event consumers: map domain events to notifications, and clean them up.

Each handler runs under the consumer's idempotency guard, so re-delivery does not
create duplicate notifications. Aggregated kinds (see ``registry``) count each
distinct actor once, so a redelivered or repeated event never inflates a count.
"""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

# tag_handlers (post.tagged, 2C), video_handlers (media.processed, 5.2) and
# moderation_handlers (account status and notices, T7) register their
# @on_event consumers on import, as do story_handlers (story.*, 1.9).
from . import (  # noqa: F401
    commerce_handlers,
    moderation_handlers,
    services,
    story_handlers,
    tag_handlers,
    video_handlers,
)
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


@on_event("comment.deleted")
def on_comment_deleted(e: EventEnvelope) -> None:
    """A deleted comment (a root takes its replies) takes the notifications about it."""
    p = e.payload
    ids = p.get("removed_ids") or [p.get("comment_id") or e.subject_id]
    services.purge_comments([str(i) for i in ids if i])


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
    """The requester took the request back."""
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
    if p.get("type") == "system":
        return  # call logs: a missed call has its own kind (`call.missed`)
    sender = p.get("sender")
    muted = {str(m) for m in p.get("muted", [])}
    conversation_id = p["conversation_id"]
    # A page or support team's reply: sent as the Page or as Tara Support, so
    # there is no person to name (``sender`` is the page id or a fixed id).
    sender_as = p.get("sender_as") or {}
    data = {
        "conversation_id": conversation_id,
        "message_id": p.get("message_id") or e.subject_id,
        "message_type": p.get("type"),
    }
    if sender_as:
        data["sender_kind"] = sender_as.get("kind")
        data["sender_name"] = sender_as.get("name")
        if sender_as.get("kind") == "page":
            data["page_id"] = sender_as.get("id")
    for recipient in p.get("recipients", []):
        if str(recipient) != str(sender) and str(recipient) not in muted:
            notify(
                recipient,
                "message",
                actor_id=None if sender_as else sender,
                subject_ref=f"conversation:{conversation_id}",
                group_key=str(conversation_id),
                # Attachment-only messages have no text; the client words those.
                body=p.get("preview") or "",
                data=data,
            )
    # A member wrote to a Page: its team is not in the conversation, so it hears
    # of it here (one row per thread, opening the page inbox on that thread).
    team = p.get("team") or {}
    if team.get("kind") == "page" and team.get("page_id"):
        team_data = {
            **data,
            "page_id": team["page_id"],
            "page_name": team.get("name") or "",
        }
        for recipient in team.get("recipients") or []:
            if str(recipient) != str(sender):
                notify(
                    recipient,
                    "message.page",
                    actor_id=sender,
                    subject_ref=f"conversation:{conversation_id}",
                    group_key=str(conversation_id),
                    body=p.get("preview") or "",
                    data=team_data,
                )
    # A member wrote to Tara Support: the support team (chat asks identity who
    # holds moderation.case.view) hears of it, opening the support inbox.
    elif team.get("kind") == "support":
        for recipient in team.get("recipients") or []:
            if str(recipient) != str(sender):
                notify(
                    recipient,
                    "message.support",
                    actor_id=sender,
                    subject_ref=f"conversation:{conversation_id}",
                    group_key=str(conversation_id),
                    body=p.get("preview") or "",
                    data=data,
                )


@on_event("message.deleted")
def on_message_deleted(e: EventEnvelope) -> None:
    """Deleted for everyone, or removed by moderation: its preview (or its row) goes."""
    p = e.payload
    if p.get("conversation_id"):
        message_id = p.get("message_id") or e.subject_id
        services.forget_message(p["conversation_id"], message_id, deleted=True)


@on_event("message.edited")
def on_message_edited(e: EventEnvelope) -> None:
    """The preview shows text the sender has since changed: it goes (events carry no text)."""
    p = e.payload
    if p.get("conversation_id"):
        message_id = p.get("message_id") or e.subject_id
        services.forget_message(p["conversation_id"], message_id, deleted=False)


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


# ---- events (gatherings, post service 1.13) ---------------------------------------
# Payloads carry ids and enums only; the client words each kind and links to
# /events/<id> (registry.build_url). Recipient lists arrive in chunks.


def _gathering(p: dict) -> tuple[str, dict]:
    gathering_id = p["gathering_id"]
    return f"gathering:{gathering_id}", {"gathering_id": gathering_id}


@on_event("gathering.invited")
def on_gathering_invited(e: EventEnvelope) -> None:
    p = e.payload
    ref, data = _gathering(p)
    for invitee in p.get("invitee_ids", []):
        notify(
            invitee,
            "gathering.invite",
            actor_id=p.get("host_id"),
            subject_ref=ref,
            body="invited you to an event",
            data=data,
        )


@on_event("gathering.reminder")
def on_gathering_reminder(e: EventEnvelope) -> None:
    """No actor: the host gets the reminder too."""
    p = e.payload
    ref, data = _gathering(p)
    for recipient in p.get("recipients", []):
        notify(
            recipient,
            "gathering.reminder",
            subject_ref=ref,
            body="an event you're going to starts soon",
            data={**data, "window": p.get("window")},
        )


@on_event("gathering.updated")
def on_gathering_updated(e: EventEnvelope) -> None:
    """Only a change of time or place (``notify``) is news to the people coming."""
    p = e.payload
    if not p.get("notify"):
        return
    ref, data = _gathering(p)
    for recipient in p.get("recipients", []):
        notify(
            recipient,
            "gathering.update",
            actor_id=p.get("host_id"),
            subject_ref=ref,
            body="changed the time or place of an event",
            data=data,
        )


@on_event("gathering.cancelled")
def on_gathering_cancelled(e: EventEnvelope) -> None:
    p = e.payload
    ref, data = _gathering(p)
    for recipient in p.get("recipients", []):
        notify(
            recipient,
            "gathering.cancel",
            actor_id=p.get("host_id"),
            subject_ref=ref,
            body="cancelled an event",
            data=data,
        )


@on_event("gathering.rsvp")
def on_gathering_rsvp(e: EventEnvelope) -> None:
    """The host hears about new going and interested answers, grouped per event.
    Switching between the two, or saying no, is not news."""
    p = e.payload
    if p.get("status") not in ("going", "interested"):
        return
    if p.get("previous_status") in ("going", "interested"):
        return
    ref, data = _gathering(p)
    notify(
        p["host_id"],
        "gathering.rsvp",
        actor_id=p.get("account_id"),
        subject_ref=ref,
        body="responded to your event",
        data={**data, "status": p.get("status")},
    )


@on_event("gathering.deleted")
def on_gathering_deleted(e: EventEnvelope) -> None:
    """Deleted by the host or removed by moderation: its notifications go too."""
    gathering_id = e.payload.get("gathering_id") or e.subject_id
    if gathering_id:
        services.purge_subject(f"gathering:{gathering_id}")


# ---- calls (roadmap 3.7): a push-only ring path, plus an in-app missed call ----------


def _call_push(recipient, push_kind: str, p: dict, **extra) -> None:
    """Queue one push-only call message (no notification row) after commit."""
    from urllib.parse import quote

    from django.db import transaction

    from . import tasks

    conversation_id = str(p.get("conversation_id") or "")
    data = {
        "kind": push_kind,
        "tag": f"call:{p.get('call_id')}",
        "call_id": str(p.get("call_id")),
        "conversation_id": conversation_id,
        "url": f"/messages/{quote(conversation_id, safe='')}",
        **extra,
    }
    recipient_id = str(recipient)

    def queue() -> None:
        try:
            tasks.deliver_call_push.delay(recipient_id, data)
        except Exception:  # noqa: BLE001 - a ring is best effort
            services.logger.warning("could not queue a call push", exc_info=True)

    transaction.on_commit(queue)


@on_event("call.started")
def on_call_started(e: EventEnvelope) -> None:
    """Ring every callee's browsers. No in-app row: ringing is not list spam."""
    p = e.payload
    for recipient in p.get("recipients") or []:
        _call_push(recipient, "call.ring", p, call_kind=p.get("kind"), body="")


@on_event("call.answered")
def on_call_answered(e: EventEnvelope) -> None:
    """Answered on one device: the ring on the answerer's other devices clears."""
    p = e.payload
    if p.get("account"):
        _call_push(p["account"], "call.clear", p, reason="answered")


@on_event("call.declined")
def on_call_declined(e: EventEnvelope) -> None:
    p = e.payload
    if p.get("account"):
        _call_push(p["account"], "call.clear", p, reason="declined")


@on_event("call.ended")
def on_call_ended(e: EventEnvelope) -> None:
    """Only those still ringing have something to clear."""
    p = e.payload
    for recipient in p.get("ringing") or []:
        _call_push(recipient, "call.clear", p, reason="ended")


@on_event("call.missed")
def on_call_missed(e: EventEnvelope) -> None:
    """An in-app "missed call" row, and the ring replaced by a missed-call push."""
    p = e.payload
    conversation_id = p.get("conversation_id")
    for recipient in p.get("missed") or []:
        notify(
            recipient,
            "call.missed",
            actor_id=p.get("initiator"),
            subject_ref=f"conversation:{conversation_id}",
            group_key=f"call:{p.get('call_id')}",
            data={
                "conversation_id": conversation_id,
                "call_id": p.get("call_id"),
                "call_kind": p.get("kind"),
            },
        )
        _call_push(recipient, "call.missed", p, call_kind=p.get("kind"), body="")


# ---- groups (profile 1.11; posts and announcements from post) -----------------------
# Payloads carry ids and enums only. Links open /groups/<handle>; a hidden group's
# handle never travels, so its links use the id (the app accepts both).


def _group(p: dict) -> tuple[str, dict]:
    group_id = p["group_id"]
    return f"group:{group_id}", {"group_id": group_id, "group_handle": p.get("handle") or None}


@on_event("group.member.changed")
def on_group_member_changed(e: EventEnvelope) -> None:
    """Invites, requests (to the group's staff, one row per group), approvals and
    role changes. Leaving, removals and bans tell nobody."""
    p = e.payload
    action = p.get("action")
    ref, data = _group(p)
    account = p.get("account_id")
    if action == "invited":
        notify(account, "group.invite", actor_id=e.actor_id, subject_ref=ref, data=data)
    elif action == "requested":
        for recipient in p.get("recipients") or []:
            notify(recipient, "group.request", actor_id=account, subject_ref=ref, data=data)
    elif action == "approved":
        notify(account, "group.approved", actor_id=e.actor_id, subject_ref=ref, data=data)
    elif action == "role_changed" and p.get("role"):
        notify(
            account,
            "group.role",
            actor_id=e.actor_id,
            subject_ref=ref,
            data={**data, "role": p["role"]},
        )


@on_event("group.post.published")
def on_group_post_published(e: EventEnvelope) -> None:
    """Members who opted in for the group, one row per group until read."""
    p = e.payload
    ref, data = _group(p)
    for recipient in p.get("recipients") or []:
        notify(
            recipient,
            "group.post",
            actor_id=p.get("author_id"),
            subject_ref=ref,
            target_ref=f"post:{p['post_id']}",
            data={**data, "post_id": p["post_id"]},
        )


@on_event("group.announcement.pinned")
def on_group_announcement(e: EventEnvelope) -> None:
    p = e.payload
    ref, data = _group(p)
    for recipient in p.get("recipients") or []:
        notify(
            recipient,
            "group.announcement",
            actor_id=e.actor_id,
            subject_ref=ref,
            target_ref=f"post:{p['post_id']}",
            data={**data, "post_id": p["post_id"]},
        )


@on_event("group.deleted")
def on_group_deleted(e: EventEnvelope) -> None:
    """Deleted by its owner or removed by moderation: its notifications go too."""
    group_id = e.payload.get("group_id") or e.subject_id
    if group_id:
        services.purge_subject(f"group:{group_id}")
