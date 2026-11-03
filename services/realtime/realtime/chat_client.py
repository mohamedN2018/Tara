"""Asks Chat whether an account belongs to a conversation."""

from __future__ import annotations

import logging
import time

import jwt
import requests
from django.conf import settings

logger = logging.getLogger("tara.realtime.chat_client")


def is_member(conversation_id: str, account_id: str) -> bool:
    """Fails closed: if Chat cannot answer, the subscription is refused."""
    now = int(time.time())
    token = jwt.encode(
        {"iss": "realtime", "aud": "chat-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    url = (
        f"{settings.CHAT_INTERNAL_URL}/internal/v1/conversations/"
        f"{conversation_id}/members/{account_id}/"
    )
    try:
        response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=2)
        response.raise_for_status()
        return bool(response.json()["data"]["is_member"])
    except (requests.RequestException, KeyError, ValueError):
        logger.warning("membership check failed", extra={"conversation_id": conversation_id})
        return False
