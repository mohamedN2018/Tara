"""Event-bus → WebSocket bridge.

Registers @on_event handlers that push domain events to the relevant user
groups via the channel layer. Run by the `consume_events` command (a kombu
consumer). The gateway keeps no source of truth — it only fans events out to
connected sockets; missed pushes are recovered by clients via REST/polling.
"""

from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import peers
from .groups import user_group

logger = logging.getLogger("tara.realtime.bridge")


def _push_to_user(account_id: str, data: dict) -> None:
    layer = get_channel_layer()
    async_to_sync(layer.group_send)(user_group(str(account_id)), {"type": "push", "data": data})


@on_event("message.created")
def on_message_created(event: EventEnvelope) -> None:
    p = event.payload
    data = {
        "event": "chat.message.created",
        "conversation_id": p.get("conversation_id"),
        "message_id": p.get("message_id"),
        "sender": p.get("sender"),
        "type": p.get("type"),
        "seq": p.get("seq"),
        "preview": p.get("preview"),
    }
    muted = set(p.get("muted", []))
    for recipient in p.get("recipients", []):
        _push_to_user(recipient, {**data, "muted": recipient in muted})


@on_event("message.read")
def on_message_read(event: EventEnvelope) -> None:
    p = event.payload
    data = {
        "event": "chat.message.read",
        "conversation_id": p.get("conversation_id"),
        "reader": p.get("reader"),
        "up_to_message_id": p.get("up_to_message_id"),
        "up_to_seq": p.get("up_to_seq"),
    }
    for recipient in p.get("recipients", []):
        _push_to_user(recipient, data)


@on_event("message.delivered")
def on_message_delivered(event: EventEnvelope) -> None:
    p = event.payload
    data = {
        "event": "chat.message.delivered",
        "conversation_id": p.get("conversation_id"),
        "account": p.get("account"),
        "up_to_seq": p.get("up_to_seq"),
    }
    for recipient in p.get("recipients", []):
        _push_to_user(recipient, data)


@on_event("message.edited")
def on_message_edited(event: EventEnvelope) -> None:
    """Frames carry ids only; clients refetch the message over REST."""
    p = event.payload
    data = {
        "event": "chat.message.edited",
        "conversation_id": p.get("conversation_id"),
        "message_id": p.get("message_id"),
    }
    for recipient in p.get("recipients", []):
        _push_to_user(recipient, data)


@on_event("message.deleted")
def on_message_deleted(event: EventEnvelope) -> None:
    """Deleted for everyone (tombstone) or removed by moderation (gone)."""
    p = event.payload
    data = {
        "event": "chat.message.deleted",
        "conversation_id": p.get("conversation_id"),
        "message_id": p.get("message_id"),
        "scope": p.get("scope"),
    }
    for recipient in p.get("recipients", []):
        _push_to_user(recipient, data)


# ---- presence audience changes -------------------------------------------------


def _hide_presence(a: str, b: str) -> None:
    """Drop cached verdicts and blank each side's view of the other right away."""
    peers.invalidate(a, b)
    for viewer, target in ((a, b), (b, a)):
        _push_to_user(
            viewer,
            {"event": "presence.changed", "account_id": target, "online": False, "last_seen": None},
        )


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    if p.get("blocker_id") and p.get("blocked_id"):
        _hide_presence(str(p["blocker_id"]), str(p["blocked_id"]))


@on_event("friendship.removed")
def on_friendship_removed(event: EventEnvelope) -> None:
    p = event.payload
    if p.get("a") and p.get("b"):
        # They may still share a DM; the next query re-derives the verdict.
        peers.invalidate(str(p["a"]), str(p["b"]))


@on_event("friendship.accepted")
def on_friendship_accepted(event: EventEnvelope) -> None:
    p = event.payload
    peers.invalidate(str(p.get("a") or ""), str(p.get("b") or ""))


@on_event("user.unblocked")
def on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    peers.invalidate(str(p.get("blocker_id") or ""), str(p.get("blocked_id") or ""))


@on_event("message.reacted")
def on_message_reacted(event: EventEnvelope) -> None:
    p = event.payload
    data = {
        "event": "chat.message.reacted",
        "conversation_id": p.get("conversation_id"),
        "message_id": p.get("message_id"),
        "reactor": p.get("reactor"),
        "type": p.get("type"),
    }
    for recipient in p.get("recipients", []):
        _push_to_user(recipient, data)


@on_event("conversation.member.changed")
def on_conversation_changed(event: EventEnvelope) -> None:
    p = event.payload
    data = {
        "event": "chat.conversation.changed",
        "conversation_id": p.get("conversation_id"),
        "action": p.get("action"),
    }
    for recipient in p.get("recipients", []):
        _push_to_user(recipient, data)


@on_event("notification.created")
def on_notification_created(event: EventEnvelope) -> None:
    p = event.payload
    recipient = p.get("recipient")
    if recipient:
        _push_to_user(
            recipient,
            {
                "event": "notification.created",
                "kind": p.get("kind"),
                "notification_id": event.subject_id,
            },
        )


@on_event("notification.read")
def on_notification_read(event: EventEnvelope) -> None:
    """Sync read state to the recipient's other devices (tabs use BroadcastChannel)."""
    p = event.payload
    recipient = p.get("recipient")
    if recipient:
        _push_to_user(
            recipient,
            {
                "event": "notification.read",
                "notification_ids": [str(i) for i in (p.get("notification_ids") or [])][:100],
                "all": bool(p.get("all")),
            },
        )


@on_event("notification.deleted")
def on_notification_deleted(event: EventEnvelope) -> None:
    p = event.payload
    recipient = p.get("recipient")
    ids = [str(i) for i in (p.get("notification_ids") or [])][:100]
    if recipient and ids:
        _push_to_user(recipient, {"event": "notification.deleted", "notification_ids": ids})


@on_event("feed.item.added")
def on_feed_item_added(event: EventEnvelope) -> None:
    p = event.payload
    data = {
        "event": "feed.item.added",
        "post_id": p.get("post_id"),
        "author_id": p.get("author_id"),
    }
    # Rows queued before the summary event carry a single `recipient`.
    recipients = p.get("recipients") or ([p["recipient"]] if p.get("recipient") else [])
    for recipient in recipients:
        _push_to_user(recipient, data)
