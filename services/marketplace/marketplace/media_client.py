"""Media client: what a listing's attachments are, asked before the listing is written.

Fails closed. If media cannot answer, the listing is not created (503), so a
video, an unfinished upload or someone else's file is never attached unchecked.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import jwt
import requests
from django.conf import settings

from tara_common.exceptions import TaraAPIError
from tara_resilience import CircuitBreaker

logger = logging.getLogger("tara.marketplace.media_client")
_breaker = CircuitBreaker(name="media", failure_threshold=5, recovery_timeout=20.0)


@dataclass(frozen=True)
class MediaInfo:
    id: str
    owner_id: str
    kind: str
    status: str


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "marketplace", "aud": "media-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def _unavailable() -> TaraAPIError:
    return TaraAPIError(
        "Media service is unavailable; try again.",
        code="dependency_unavailable",
        http_status_code=503,
    )


def lookup(media_ids: list[str]) -> dict[str, MediaInfo]:
    """``{media_id: MediaInfo}``; ids media does not know (or deleted) are absent."""

    def _call() -> dict[str, MediaInfo]:
        resp = requests.post(
            f"{settings.MEDIA_INTERNAL_URL}/internal/v1/media/batch/",
            json={"ids": [str(m) for m in media_ids]},
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.MEDIA_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        # A malformed answer fails closed like an outage.
        return {
            r["id"]: MediaInfo(
                id=r["id"], owner_id=r["owner_id"], kind=r["kind"], status=r["status"]
            )
            for r in resp.json()["data"]
        }

    try:
        return _breaker.call(_call)
    except Exception as exc:  # noqa: BLE001 - circuit open, timeout, error: fail closed
        logger.warning("media lookup failed", exc_info=True)
        raise _unavailable() from exc
