"""The only module that talks to LiveKit, through the official `livekit-api` SDK.

* ``enabled()``: calls are on only when the key, the secret and the public URL
  are all set. Otherwise every call endpoint answers 503 ``calls_unavailable``.
* ``mint_token``: a join token for one room, with the account id as identity
  and a TTL of at most ``MAX_TOKEN_TTL_SECONDS``.
* ``receive_webhook``: verifies a webhook's signed Authorization token and the
  SHA-256 of the raw body it carries (``WebhookReceiver``).
* ``remove_participant`` / ``delete_room`` / ``room_identities``: the server API,
  used from Celery tasks only, never inside a request transaction.

The secret is read from settings each time and never logged.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp
from django.conf import settings
from livekit import api

logger = logging.getLogger("tara.chat.calls.livekit")

MAX_TOKEN_TTL_SECONDS = 600


class LiveKitUnavailable(Exception):
    """The LiveKit server API could not be reached or failed (retryable)."""


def enabled() -> bool:
    return bool(settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET and settings.LIVEKIT_URL)


def token_ttl_seconds() -> int:
    return max(30, min(int(settings.CALL_TOKEN_TTL_SECONDS), MAX_TOKEN_TTL_SECONDS))


def mint_token(room: str, identity: str) -> str:
    """Join, publish and subscribe in ``room`` only. No admin, list or record grants."""
    grants = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
        can_publish_sources=["camera", "microphone", "screen_share", "screen_share_audio"],
        can_update_own_metadata=False,
    )
    return (
        api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(str(identity))
        .with_grants(grants)
        .with_ttl(timedelta(seconds=token_ttl_seconds()))
        .to_jwt()
    )


def receive_webhook(body: str, auth_header: str):
    """The verified ``WebhookEvent``. Raises on a bad signature or body hash."""
    token = (auth_header or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise ValueError("missing webhook token")
    verifier = api.TokenVerifier(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
    return api.WebhookReceiver(verifier).receive(body, token)


async def _with_api(action):
    timeout = aiohttp.ClientTimeout(total=float(settings.LIVEKIT_API_TIMEOUT))
    client = api.LiveKitAPI(
        settings.LIVEKIT_INTERNAL_URL,
        settings.LIVEKIT_API_KEY,
        settings.LIVEKIT_API_SECRET,
        timeout=timeout,
        failover=False,  # region failover is for LiveKit Cloud
    )
    try:
        return await action(client)
    finally:
        await client.aclose()


def _run(action, what: str):
    if not (settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET):
        return None
    try:
        return asyncio.run(_with_api(action))
    except api.ServerError as exc:
        if exc.code == api.ServerErrorCode.NOT_FOUND:
            return None  # the room or the participant is already gone
        logger.warning("livekit %s failed", what, extra={"code": exc.code})
        raise LiveKitUnavailable(what) from exc
    except (aiohttp.ClientError, TimeoutError, OSError) as exc:
        logger.warning("livekit %s unreachable", what)
        raise LiveKitUnavailable(what) from exc


def remove_participant(room: str, identity: str) -> None:
    _run(
        lambda c: c.room.remove_participant(
            api.RoomParticipantIdentity(room=room, identity=str(identity))
        ),
        "remove_participant",
    )


def delete_room(room: str) -> None:
    _run(lambda c: c.room.delete_room(api.DeleteRoomRequest(room=room)), "delete_room")


def room_identities(room: str) -> list[str] | None:
    """Identities in the room right now; ``None`` when the room does not exist."""

    async def action(client):
        response = await client.room.list_participants(api.ListParticipantsRequest(room=room))
        return [p.identity for p in response.participants]

    return _run(action, "list_participants")
