"""Media client: what a creative's image is, asked before the creative is written.

Fails closed. If media cannot answer, the creative is not created (503), so an
unfinished upload, a video or someone else's file is never attached unchecked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

from tara_common.auth import mint_internal_token
from tara_common.exceptions import TaraAPIError
from tara_resilience import CircuitBreaker

logger = logging.getLogger("tara.ads.media_client")
_breaker = CircuitBreaker(name="media", failure_threshold=5, recovery_timeout=20.0)


@dataclass(frozen=True)
class MediaInfo:
    id: str
    owner_id: str
    kind: str
    status: str


def _unavailable() -> TaraAPIError:
    return TaraAPIError(
        "Media service is unavailable; try again.",
        code="dependency_unavailable",
        http_status_code=503,
    )


def lookup(media_ids: list[str]) -> dict[str, MediaInfo]:
    """``{media_id: MediaInfo}``; ids media does not know (or deleted) are absent."""

    def _call() -> dict[str, MediaInfo]:
        token = mint_internal_token(issuer="ads", audience="media-internal")
        resp = requests.post(
            f"{settings.MEDIA_INTERNAL_URL}/internal/v1/media/batch/",
            json={"ids": [str(m) for m in media_ids]},
            headers={"Authorization": f"Bearer {token}"},
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
