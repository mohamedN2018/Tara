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
        "preview": p.get("preview"),
    }
    for recipient in p.get("recipients", []):
        _push_to_user(recipient, data)


@on_event("message.read")
def on_message_read(event: EventEnvelope) -> None:
    p = event.payload
    data = {
        "event": "chat.message.read",
        "conversation_id": p.get("conversation_id"),
        "reader": p.get("reader"),
        "up_to_message_id": p.get("up_to_message_id"),
    }
    for recipient in p.get("recipients", []):
        _push_to_user(recipient, data)


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
