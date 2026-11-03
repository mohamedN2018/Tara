"""WebSocket consumer: authenticated channels, presence, typing, subscriptions.

Auth: an access token is supplied as ``?token=...`` on connect and verified
locally (JWKS/PEM). The socket joins the connecting account's user group so the
event-bus bridge can push chat/notification/feed events to it. Clients subscribe
to conversation groups to send/receive typing indicators.

Presence (see ``presence``): every frame, pings included, is a heartbeat. The
first socket of an account announces "online" and the last one to close
announces "offline" with ``last_seen``; announcements go only to the account's
authorised peers (``peers.audience``), never to a global group. A client asks
for peers' current state with ``{"action": "presence.query", "account_ids": [...]}``
and gets back only the ones it is allowed to see.
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from . import chat_client, peers, presence
from .auth import verify_access_token
from .groups import conversation_group, user_group

logger = logging.getLogger("tara.realtime.consumer")

CLOSE_UNAUTHENTICATED = 4401
MAX_SUBSCRIPTIONS = 200


async def announce(account_id: str, online: bool) -> None:
    """Tell the account's peers it came online or went offline."""
    from channels.layers import get_channel_layer

    try:
        audience = await sync_to_async(peers.audience)(account_id)
        state = await sync_to_async(presence.state)(account_id)
    except Exception:  # noqa: BLE001 - presence is best-effort, never break the socket
        logger.warning("presence announce failed", exc_info=True)
        return
    frame = {
        "event": "presence.changed",
        "account_id": account_id,
        "online": online,
        "last_seen": None if online else state["last_seen"],
    }
    layer = get_channel_layer()
    for peer in audience:
        await layer.group_send(user_group(peer), {"type": "push", "data": frame})


class TaraConsumer(AsyncJsonWebsocketConsumer):
    async def _close_at(self, expires_at: int) -> None:
        await asyncio.sleep(max(0, expires_at - time.time()))
        await self.close(code=CLOSE_UNAUTHENTICATED)

    async def connect(self) -> None:
        token = self._token_from_scope()
        if not token:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        try:
            claims = await sync_to_async(verify_access_token)(token)
        except Exception:  # noqa: BLE001 - any verification failure rejects the socket
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        self.account_id = str(claims["sub"])
        self.subscriptions: set[str] = set()
        self.typing_at: dict[str, float] = {}
        # The socket lives no longer than its token; the client reconnects with a new one.
        self.expiry_task = asyncio.create_task(self._close_at(claims["exp"]))
        await self.channel_layer.group_add(user_group(self.account_id), self.channel_name)
        await self.accept()
        await self.send_json({"event": "connected", "account_id": self.account_id})
        await self._heartbeat(first=True)

    async def disconnect(self, code) -> None:
        account_id = getattr(self, "account_id", None)
        if account_id is None:
            return
        self.expiry_task.cancel()
        await self.channel_layer.group_discard(user_group(account_id), self.channel_name)
        for conv_id in getattr(self, "subscriptions", set()):
            await self.channel_layer.group_discard(conversation_group(conv_id), self.channel_name)
        try:
            last_out = await sync_to_async(presence.disconnect)(account_id, self.channel_name)
        except Exception:  # noqa: BLE001 - the key expires on its own anyway
            logger.warning("presence disconnect failed", exc_info=True)
            return
        if last_out:
            await announce(account_id, online=False)

    async def _heartbeat(self, first: bool = False) -> None:
        try:
            came_online = await sync_to_async(presence.connect if first else presence.heartbeat)(
                self.account_id, self.channel_name
            )
        except Exception:  # noqa: BLE001 - Redis down: no presence, socket still works
            logger.warning("presence heartbeat failed", exc_info=True)
            return
        if came_online:
            asyncio.create_task(announce(self.account_id, online=True))

    async def receive_json(self, content, **kwargs) -> None:
        if not isinstance(content, dict):
            return
        action = content.get("action")
        await self._heartbeat()
        if action == "ping":
            await self.send_json({"event": "pong"})
        elif action == "presence.query":
            await self._presence_query(content.get("account_ids"))
        elif action == "subscribe":
            conv_id = str(content.get("conversation_id", ""))
            if (
                conv_id
                and len(self.subscriptions) < MAX_SUBSCRIPTIONS
                and await sync_to_async(chat_client.is_member)(conv_id, self.account_id)
            ):
                self.subscriptions.add(conv_id)
                await self.channel_layer.group_add(conversation_group(conv_id), self.channel_name)
        elif action == "unsubscribe":
            conv_id = str(content.get("conversation_id", ""))
            self.subscriptions.discard(conv_id)
            await self.channel_layer.group_discard(conversation_group(conv_id), self.channel_name)
        elif action == "typing":
            conv_id = str(content.get("conversation_id", ""))
            now = time.monotonic()
            # At most one typing frame per conversation every TYPING_MIN_INTERVAL.
            if (
                conv_id in self.subscriptions
                and now - self.typing_at.get(conv_id, 0.0) >= settings.TYPING_MIN_INTERVAL
            ):
                self.typing_at[conv_id] = now
                await self.channel_layer.group_send(
                    conversation_group(conv_id),
                    {
                        "type": "typing.event",
                        "payload": {
                            "event": "conversation.typing",
                            "conversation_id": conv_id,
                            "actor_id": self.account_id,
                        },
                    },
                )

    async def _presence_query(self, account_ids) -> None:
        if not isinstance(account_ids, list):
            return
        wanted = {str(a) for a in account_ids[: settings.PRESENCE_QUERY_MAX] if a}
        allowed = await sync_to_async(peers.audience)(self.account_id)
        visible = sorted(wanted & allowed)
        states = [await sync_to_async(presence.state)(a) for a in visible]
        await self.send_json({"event": "presence.state", "states": states})

    # ---- channel-layer message handlers (type -> method, dots become _) ----

    async def push(self, event) -> None:
        await self.send_json(event["data"])

    async def typing_event(self, event) -> None:
        await self.send_json(event["payload"])

    # ---- helpers ----

    def _token_from_scope(self) -> str | None:
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        if "token" in qs:
            return qs["token"][0]
        # Fallback: token in the Sec-WebSocket-Protocol header.
        for name, value in self.scope.get("headers", []):
            if name == b"sec-websocket-protocol":
                return value.decode().split(",")[0].strip()
        return None
