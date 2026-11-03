"""Internal reads from Chat: membership and presence peers.

Both fail closed: if Chat cannot answer, a subscription is refused and a
presence audience is empty (nobody is told, nobody is shown).
"""

from __future__ import annotations

import logging
import time

import jwt
import requests
from django.conf import settings

logger = logging.getLogger("tara.realtime.chat_client")


def _token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "realtime", "aud": "chat-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def _get(path: str) -> dict:
    response = requests.get(
        f"{settings.CHAT_INTERNAL_URL}/internal/v1/{path}",
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=settings.INTERNAL_CALL_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["data"]


def is_member(conversation_id: str, account_id: str) -> bool:
    """Fails closed: if Chat cannot answer, the subscription is refused."""
    try:
        return bool(_get(f"conversations/{conversation_id}/members/{account_id}/")["is_member"])
    except (requests.RequestException, KeyError, ValueError):
        logger.warning("membership check failed", extra={"conversation_id": conversation_id})
        return False


def presence_peers(account_id: str) -> list[str] | None:
    """DM peers allowed to see this account's presence; None when Chat failed."""
    try:
        return [str(p) for p in _get(f"accounts/{account_id}/presence-peers/")["peers"]]
    except (requests.RequestException, KeyError, ValueError, TypeError):
        logger.warning("presence peers lookup failed")
        return None
