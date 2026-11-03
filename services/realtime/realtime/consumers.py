"""WebSocket consumer: authenticated channels, presence, typing, subscriptions.

Auth: an access token is supplied as ``?token=...`` on connect and verified
locally (JWKS/PEM). The socket joins the connecting account's user group so the
event-bus bridge can push chat/notification/feed events to it. Clients subscribe
to conversation groups to send/receive typing indicators.
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from . import chat_client, presence
from .auth import verify_access_token
from .groups import conversation_group, user_group

logger = logging.getLogger("tara.realtime.consumer")

CLOSE_UNAUTHENTICATED = 4401
MAX_SUBSCRIPTIONS = 200


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
        # The socket lives no longer than its token; the client reconnects with a new one.
        self.expiry_task = asyncio.create_task(self._close_at(claims["exp"]))
        await self.channel_layer.group_add(user_group(self.account_id), self.channel_name)
        await sync_to_async(presence.mark_online)(self.account_id)
        await self.accept()
        await self.send_json({"event": "connected", "account_id": self.account_id})

    async def disconnect(self, code) -> None:
        account_id = getattr(self, "account_id", None)
        if account_id is None:
            return
        self.expiry_task.cancel()
        await self.channel_layer.group_discard(user_group(account_id), self.channel_name)
        for conv_id in getattr(self, "subscriptions", set()):
            await self.channel_layer.group_discard(conversation_group(conv_id), self.channel_name)
        await sync_to_async(presence.mark_offline)(account_id)

    async def receive_json(self, content, **kwargs) -> None:
        action = content.get("action")
        if action == "ping":
            await self.send_json({"event": "pong"})
            return
        await sync_to_async(presence.refresh)(self.account_id)

        if action == "subscribe":
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
            if conv_id in self.subscriptions:
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
