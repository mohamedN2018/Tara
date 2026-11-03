"""Internal read from Graph: an account's friends (blocked pairs excluded by Graph)."""

from __future__ import annotations

import logging
import time

import jwt
import requests
from django.conf import settings

logger = logging.getLogger("tara.realtime.graph_client")


def friends(account_id: str) -> list[str] | None:
    """None when Graph cannot answer (the caller then fails closed)."""
    now = int(time.time())
    token = jwt.encode(
        {"iss": "realtime", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    try:
        response = requests.get(
            f"{settings.GRAPH_INTERNAL_URL}/internal/v1/fanout/{account_id}/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.INTERNAL_CALL_TIMEOUT,
        )
        response.raise_for_status()
        return [str(f) for f in response.json()["data"]["friends"]]
    except (requests.RequestException, KeyError, ValueError, TypeError):
        logger.warning("friends lookup failed")
        return None
