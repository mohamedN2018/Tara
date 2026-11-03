"""Media client: validate attachments, and mint URLs for members.

Chat never signs URLs itself: media owns the bytes and the signatures. Chat
checks membership and that the attachment belongs to a message the caller can
see, then asks media's internal API for a presigned URL. Every failure raises
(fail closed): a 503 when media cannot answer, never an unchecked attachment.
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

logger = logging.getLogger("tara.chat.media_client")
_breaker = CircuitBreaker(name="media", failure_threshold=5, recovery_timeout=20.0)


@dataclass(frozen=True)
class MediaInfo:
    id: str
    owner_id: str
    kind: str
    status: str
    mime: str
    bytes: int
    visibility: str


class MediaNotFound(Exception):
    pass


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "chat", "aud": "media-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def _unavailable() -> TaraAPIError:
    return TaraAPIError(
        "Media service is unavailable; try again.",
        code="dependency_unavailable",
        http_status_code=503,
    )


def _request(method: str, path: str, body: dict | None = None):
    def _call():
        resp = requests.request(
            method,
            f"{settings.MEDIA_INTERNAL_URL}/internal/v1/{path}",
            json=body,
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.MEDIA_CALL_TIMEOUT,
        )
        if resp.status_code == 404:
            return None  # a definite answer, not a failure of media
        resp.raise_for_status()
        return resp.json()["data"]

    try:
        return _breaker.call(_call)
    except Exception as exc:  # noqa: BLE001 - circuit open, timeout, error: fail closed
        logger.warning("media call failed", extra={"path": path}, exc_info=True)
        raise _unavailable() from exc


def lookup(media_ids: list[str]) -> dict[str, MediaInfo]:
    """``{media_id: MediaInfo}``; ids media does not know (or deleted) are absent."""
    rows = _request("POST", "media/batch/", {"ids": [str(m) for m in media_ids]}) or []
    return {
        r["id"]: MediaInfo(
            id=r["id"],
            owner_id=str(r["owner_id"]),
            kind=r["kind"],
            status=r["status"],
            mime=r.get("mime") or "",
            bytes=int(r.get("bytes") or 0),
            visibility=r.get("visibility") or "public",
        )
        for r in rows
    }


def signed(media_id: str) -> dict:
    """The asset with presigned URLs (``url`` is null until it is ready).

    Raises ``MediaNotFound`` when media has no such asset.
    """
    data = _request("GET", f"media/{media_id}/")
    if data is None:
        raise MediaNotFound(media_id)
    return data
