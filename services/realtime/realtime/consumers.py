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

Limits: a frame over ``WS_MAX_FRAME_BYTES`` closes the socket (1009); frames
beyond the per-socket token bucket (``WS_FRAME_BURST``, refilled at
``WS_FRAMES_PER_SECOND``) are dropped unread; non-JSON and binary frames are
ignored. Blocking work (Redis, Chat, Graph, JWKS) runs in the thread pool, not
on one shared thread, so one slow dependency cannot stall every socket.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from . import chat_client, peers, presence
from .auth import verify_access_token
from .groups import conversation_group, user_group

logger = logging.getLogger("tara.realtime.consumer")

CLOSE_UNAUTHENTICATED = 4401
CLOSE_TOO_LARGE = 1009
MAX_SUBSCRIPTIONS = 200
# The loop keeps only weak references to tasks: hold announcements until done.
_announcements: set[asyncio.Task] = set()


def _off_loop(fn):
    """Run blocking I/O in the thread pool. The gateway has no database, so
    nothing needs Django's single "thread sensitive" thread."""
    return sync_to_async(fn, thread_sensitive=False)


def _uuid(value) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


async def announce(account_id: str, online: bool) -> None:
    """Tell the account's peers it came online or went offline."""
    from channels.layers import get_channel_layer

    try:
        audience = await _off_loop(peers.audience)(account_id)
        last_seen = None if online else (await _off_loop(presence.state)(account_id))["last_seen"]
    except Exception:  # noqa: BLE001 - presence is best-effort, never break the socket
        logger.warning("presence announce failed", exc_info=True)
        return
    frame = {
        "event": "presence.changed",
        "account_id": account_id,
        "online": online,
        "last_seen": last_seen,
    }
    layer = get_channel_layer()
    for peer in audience:
        await layer.group_send(user_group(peer), {"type": "push", "data": frame})


class TaraConsumer(AsyncJsonWebsocketConsumer):
    async def _close_at(self, expires_at: int) -> None:
        await asyncio.sleep(max(0, expires_at - time.time()))
        await self.close(code=CLOSE_UNAUTHENTICATED)

    async def connect(self) -> None:
        token, subprotocol = self._token_from_scope()
        if not token:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        try:
            claims = await _off_loop(verify_access_token)(token)
        except Exception:  # noqa: BLE001 - any verification failure rejects the socket
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        self.account_id = str(claims["sub"])
        self.subscriptions: set[str] = set()
        self.typing_at: dict[str, float] = {}
        self.allowance = float(settings.WS_FRAME_BURST)
        self.allowance_at = time.monotonic()
        # The socket lives no longer than its token; the client reconnects with a new one.
        self.expiry_task = asyncio.create_task(self._close_at(claims["exp"]))
        await self.channel_layer.group_add(user_group(self.account_id), self.channel_name)
        # A browser drops the handshake unless the server echoes an offered subprotocol.
        await self.accept(subprotocol=subprotocol)
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
            last_out = await _off_loop(presence.disconnect)(account_id, self.channel_name)
        except Exception:  # noqa: BLE001 - the key expires on its own anyway
            logger.warning("presence disconnect failed", exc_info=True)
            return
        if last_out:
            await announce(account_id, online=False)

    async def _heartbeat(self, first: bool = False) -> None:
        try:
            came_online = await _off_loop(presence.connect if first else presence.heartbeat)(
                self.account_id, self.channel_name
            )
        except Exception:  # noqa: BLE001 - Redis down: no presence, socket still works
            logger.warning("presence heartbeat failed", exc_info=True)
            return
        if came_online:
            task = asyncio.create_task(announce(self.account_id, online=True))
            _announcements.add(task)
            task.add_done_callback(_announcements.discard)

    def _take_frame(self) -> bool:
        """Token bucket: False when this socket is sending too fast."""
        now = time.monotonic()
        self.allowance = min(
            float(settings.WS_FRAME_BURST),
            self.allowance + (now - self.allowance_at) * settings.WS_FRAMES_PER_SECOND,
        )
        self.allowance_at = now
        if self.allowance < 1:
            return False
        self.allowance -= 1
        return True

    async def receive(self, text_data=None, bytes_data=None, **kwargs) -> None:
        if text_data is None:
            return  # binary frames are not part of the protocol
        if len(text_data) > settings.WS_MAX_FRAME_BYTES:
            await self.close(code=CLOSE_TOO_LARGE)
            return
        if not self._take_frame():
            return
        try:
            content = await self.decode_json(text_data)
        except ValueError:
            return
        await self.receive_json(content, **kwargs)

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
            conv_id = _uuid(content.get("conversation_id"))
            if (
                conv_id
                and conv_id not in self.subscriptions
                and len(self.subscriptions) < MAX_SUBSCRIPTIONS
                and await _off_loop(chat_client.is_member)(conv_id, self.account_id)
            ):
                self.subscriptions.add(conv_id)
                await self.channel_layer.group_add(conversation_group(conv_id), self.channel_name)
        elif action == "unsubscribe":
            conv_id = _uuid(content.get("conversation_id"))
            if conv_id:
                await self._drop_subscription(conv_id)
        elif action == "typing":
            conv_id = _uuid(content.get("conversation_id"))
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

        def lookup() -> list[dict]:
            visible = sorted(wanted & peers.audience(self.account_id))
            return [presence.state(a) for a in visible]

        try:
            states = await _off_loop(lookup)()
        except Exception:  # noqa: BLE001 - Redis down: answer nothing, keep the socket
            logger.warning("presence query failed", exc_info=True)
            return
        await self.send_json({"event": "presence.state", "states": states})

    async def _drop_subscription(self, conv_id: str) -> None:
        self.subscriptions.discard(conv_id)
        self.typing_at.pop(conv_id, None)
        await self.channel_layer.group_discard(conversation_group(conv_id), self.channel_name)

    # ---- channel-layer message handlers (type -> method, dots become _) ----

    async def push(self, event) -> None:
        await self.send_json(event["data"])

    async def typing_event(self, event) -> None:
        # Not echoed: the typist's own tabs already know.
        if event["payload"].get("actor_id") == self.account_id:
            return
        await self.send_json(event["payload"])

    async def subscription_revoke(self, event) -> None:
        """Chat says this account lost access (removed from the group, or a
        block): its live frames stop now. Silent: the client is not told."""
        conv_id = _uuid(event.get("conversation_id"))
        if conv_id:
            await self._drop_subscription(conv_id)

    # ---- helpers ----

    def _token_from_scope(self) -> tuple[str | None, str | None]:
        """``(token, subprotocol to accept)``. The token comes from ``?token=``
        or, failing that, is the first offered ``Sec-WebSocket-Protocol``
        (the ASGI server parses that header into ``scope["subprotocols"]``)."""
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        if "token" in qs:
            return qs["token"][0], None
        offered = [p.strip() for p in self.scope.get("subprotocols") or [] if p.strip()]
        if offered:
            return offered[0], offered[0]
        return None, None
