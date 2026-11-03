"""A group cover: the uploader's own image, bound to the group and restricted.

Media then asks post's visibility endpoint before it serves the cover to anyone
but the uploader; post answers for a group id from its group read model (the
same rule as the group header). Both calls run before the write transaction and
fail closed (503), so a cover is never set unchecked.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from profiles import media_client

from tara_common.auth import mint_internal_token
from tara_common.exceptions import TaraAPIError
from tara_resilience import CircuitBreaker

logger = logging.getLogger("tara.profile.groups.media")
_breaker = CircuitBreaker(name="media-bind", failure_threshold=5, recovery_timeout=20.0)


def _bad(message: str, code: str) -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=400)


def _bind(owner_id: str, group_id: str, media_id: str) -> dict:
    def _call() -> dict:
        token = mint_internal_token(issuer="profile", audience="media-internal")
        resp = requests.post(
            f"{settings.MEDIA_INTERNAL_URL}/internal/v1/media/bind/",
            json={
                "owner_id": owner_id,
                "post_id": group_id,
                "media_ids": [media_id],
                "restricted": True,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.MEDIA_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["data"]

    try:
        return _breaker.call(_call)
    except Exception as exc:  # noqa: BLE001 - circuit open, timeout, error: fail closed
        logger.warning("media bind failed", exc_info=True)
        raise TaraAPIError(
            "Media service is unavailable; try again.",
            code="dependency_unavailable",
            http_status_code=503,
        ) from exc


def check_and_bind_cover(owner_id: str, group_id: str, media_id: str) -> None:
    info = media_client.lookup([media_id]).get(media_id)
    if info is None or info.owner_id != str(owner_id):
        raise _bad("Media not found.", "media_not_owned")
    if info.kind != "image":
        raise _bad("Only an image can be a group cover.", "media_kind_not_allowed")
    if info.status not in media_client.USABLE_STATUSES:
        raise _bad("Media upload is not complete.", "media_not_ready")
    result = _bind(str(owner_id), str(group_id), str(media_id))
    if result.get("attached_elsewhere"):
        raise _bad("Media is already attached elsewhere.", "media_already_attached")
    if result.get("skipped"):
        raise _bad("Media not found.", "media_not_owned")
