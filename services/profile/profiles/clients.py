"""Client for the Social Graph internal API.

Used to resolve relationships (friend? blocked?) for `friends_only` privacy. The
call is wrapped in a circuit breaker + timeout; if Graph is unavailable we
degrade to the SAFEST assumption (not friends) rather than failing the request.
This is the synchronous-read degradation contract from doc 02 §4.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import jwt
import requests
from django.conf import settings

from tara_resilience import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("tara.profile.graph_client")

_breaker = CircuitBreaker(name="graph", failure_threshold=5, recovery_timeout=20.0)


@dataclass(frozen=True)
class Relationship:
    are_friends: bool = False
    a_follows_b: bool = False
    b_follows_a: bool = False
    blocked_either_way: bool = False
    degraded: bool = False  # True when Graph was unavailable and we defaulted

    @classmethod
    def unknown(cls) -> Relationship:
        return cls(degraded=True)


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "profile", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def get_relationship(viewer_id: str, target_id: str) -> Relationship:
    if viewer_id == target_id:
        return Relationship(are_friends=True)  # self
    url = f"{settings.GRAPH_INTERNAL_URL}/internal/v1/relationship/"

    def _call() -> Relationship:
        resp = requests.get(
            url,
            params={"a": viewer_id, "b": target_id},
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return Relationship(
            are_friends=bool(data.get("are_friends")),
            a_follows_b=bool(data.get("a_follows_b")),
            b_follows_a=bool(data.get("b_follows_a")),
            blocked_either_way=bool(data.get("blocked_either_way")),
        )

    try:
        return _breaker.call(_call)
    except CircuitOpenError:
        logger.warning("graph circuit open; defaulting relationship to not-friends")
        return Relationship.unknown()
    except Exception:  # noqa: BLE001 - any failure degrades safely
        logger.warning("graph relationship lookup failed; defaulting to not-friends", exc_info=True)
        return Relationship.unknown()
