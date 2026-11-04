"""Graph client: are two accounts friends? (message requests, plan 08 3D).

A DM a non-friend starts lands in the recipient's message requests. When graph
cannot answer, chat assumes "not friends": the message still arrives, only in
the requests folder, which is the safe side for a stranger's first message.
"""

from __future__ import annotations

import logging
import time

import jwt
import requests
from django.conf import settings

from tara_resilience import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("tara.chat.graph_client")
_breaker = CircuitBreaker(name="graph", failure_threshold=5, recovery_timeout=20.0)


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "chat", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def are_friends(a: str, b: str) -> bool | None:
    """True or False from graph; None when graph could not answer."""

    def _call() -> bool:
        resp = requests.get(
            f"{settings.GRAPH_INTERNAL_URL}/internal/v1/relationship/",
            params={"a": str(a), "b": str(b)},
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return bool(resp.json().get("data", {}).get("are_friends"))

    try:
        return _breaker.call(_call)
    except CircuitOpenError:
        logger.warning("graph circuit open; treating the DM as a message request")
        return None
    except Exception:  # noqa: BLE001 - any failure degrades to "request"
        logger.warning("graph friendship lookup failed; treating the DM as a request")
        return None


def have_mutual_friends(a: str, b: str) -> bool | None:
    """Whether ``a`` and ``b`` share a friend ("friends of friends" may
    message); None when graph could not answer."""

    def _call() -> bool:
        resp = requests.get(
            f"{settings.GRAPH_INTERNAL_URL}/internal/v1/relationship/",
            params={"a": str(a), "b": str(b), "mutual": "1"},
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        if "has_mutual_friends" not in data:
            raise ValueError("graph does not report mutual friends yet")
        return bool(data["has_mutual_friends"])

    try:
        return _breaker.call(_call)
    except CircuitOpenError:
        logger.warning("graph circuit open; cannot check mutual friends")
        return None
    except Exception:  # noqa: BLE001
        logger.warning("graph mutual-friends lookup failed")
        return None
