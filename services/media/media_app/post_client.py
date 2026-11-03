"""Ask the post service whether a viewer may see a post (for restricted media).

Visibility checks fail closed: a timeout, an error or an open circuit all mean
"no", so a post-service outage hides restricted media instead of leaking it.
"""

from __future__ import annotations

import logging
import time

import jwt
import requests
from django.conf import settings

from tara_resilience import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("tara.media.post_client")
_breaker = CircuitBreaker(name="post", failure_threshold=5, recovery_timeout=20.0)


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "media", "aud": "post-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def _visible(viewer_id: str, post_id: str) -> bool | None:
    """Post's answer, or None when it could not give one."""
    url = f"{settings.POST_INTERNAL_URL}/internal/v1/posts/{post_id}/visibility/"

    def _call() -> bool:
        resp = requests.get(
            url,
            params={"viewer_id": str(viewer_id)},
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.POST_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("visible") is True

    try:
        return _breaker.call(_call)
    except CircuitOpenError:
        logger.warning("post circuit open")
        return None
    except Exception:  # noqa: BLE001 - the callers decide, both fail closed
        logger.warning("post visibility check failed", exc_info=True)
        return None


def can_view_post(viewer_id: str, post_id: str) -> bool:
    """Whether restricted media of the post may be shown; no answer is "no"."""
    return _visible(viewer_id, post_id) is True


def post_is_live(owner_id: str, post_id: str) -> bool | None:
    """Whether the owner's post still exists and is live (its author sees it).

    False for a post that never committed, was deleted or was removed; None
    when post could not answer, which callers treat as live.
    """
    return _visible(owner_id, post_id)
