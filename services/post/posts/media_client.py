"""Media client: validate attachments, and restrict media to a post's audience.

Both calls run before post opens its write transaction. Any failure raises a
503, so a post with media is never created or narrowed while media cannot be
told (fail closed): a friends-only photo must never be public, even briefly.
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

logger = logging.getLogger("tara.post.media_client")
_breaker = CircuitBreaker(name="media", failure_threshold=5, recovery_timeout=20.0)


@dataclass(frozen=True)
class MediaInfo:
    id: str
    owner_id: str
    kind: str
    status: str
    # "post" for a video transcoded by media's pipeline (5.2); "" otherwise.
    purpose: str = ""


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "post", "aud": "media-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def _unavailable() -> TaraAPIError:
    return TaraAPIError(
        "Media service is unavailable; try again.",
        code="dependency_unavailable",
        http_status_code=503,
    )


def _post(path: str, body: dict) -> dict | list:
    def _call():
        resp = requests.post(
            f"{settings.MEDIA_INTERNAL_URL}/internal/v1/{path}",
            json=body,
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.MEDIA_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["data"]

    try:
        return _breaker.call(_call)
    except Exception as exc:  # noqa: BLE001 - circuit open, timeout, error: fail closed
        logger.warning("media call failed", extra={"path": path}, exc_info=True)
        raise _unavailable() from exc


def lookup(media_ids: list[str]) -> dict[str, MediaInfo]:
    """``{media_id: MediaInfo}``; ids media does not know (or deleted) are absent."""
    rows = _post("media/batch/", {"ids": [str(m) for m in media_ids]})
    return {
        r["id"]: MediaInfo(
            id=r["id"],
            owner_id=r["owner_id"],
            kind=r["kind"],
            status=r["status"],
            purpose=r.get("purpose") or "",
        )
        for r in rows
    }


BIND_CHUNK = 20  # media's per-call limit; older posts may carry more media


@dataclass(frozen=True)
class BindResult:
    """``skipped``: every id media did not bind to the post. ``attached_elsewhere``:
    the skipped ids that belong to another live post (the rest are deleted or
    not the owner's)."""

    skipped: list[str]
    attached_elsewhere: list[str]


def bind(owner_id: str, post_id: str, media_ids: list[str], *, restricted: bool) -> BindResult:
    """Attach media to the post, or (``restricted``) tighten them to its visibility.

    ``restricted=False`` for the same post lifts a restriction only when media,
    asking post's visibility endpoint, finds the post public (a published
    draft); otherwise restricted media keep following the post's visibility.
    """
    ids = [str(m) for m in media_ids]
    skipped: list[str] = []
    elsewhere: list[str] = []
    for start in range(0, len(ids), BIND_CHUNK):
        result = _post(
            "media/bind/",
            {
                "owner_id": str(owner_id),
                "post_id": str(post_id),
                "media_ids": ids[start : start + BIND_CHUNK],
                "restricted": restricted,
            },
        )
        skipped += result.get("skipped", [])
        elsewhere += result.get("attached_elsewhere", [])
    return BindResult(skipped=skipped, attached_elsewhere=elsewhere)
