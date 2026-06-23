"""Fetch a sponsored slot from the Ads service for the home feed.

Wrapped in a circuit breaker + timeout. If Ads is unavailable we return None so
the feed renders organic content only — "if ads fail, show organic feed"
(brief §10 / doc 02 §5).
"""

from __future__ import annotations

import logging
import time

import jwt
import requests
from django.conf import settings

from tara_resilience import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("tara.feed.ads_client")
_breaker = CircuitBreaker(name="ads", failure_threshold=5, recovery_timeout=20.0)


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "feed", "aud": "ads-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def feed_sponsored(viewer_id: str) -> dict | None:
    url = f"{settings.ADS_INTERNAL_URL}/internal/v1/ads/feed-slot/"

    def _call():
        resp = requests.get(
            url,
            params={"viewer": viewer_id, "placement": "feed"},
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.ADS_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("sponsored")

    try:
        return _breaker.call(_call)
    except CircuitOpenError:
        return None
    except Exception:  # noqa: BLE001 - ads outage must not break the feed
        logger.warning("ads feed-slot unavailable; serving organic only", exc_info=True)
        return None
