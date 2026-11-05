"""Secure video playback (roadmap 5.3).

1. ``GET /media/<id>/playback/`` (the viewer's JWT) checks access and returns a
   playback token: an HS256 token for this media and viewer, signed with a
   media-only secret (``MEDIA_PLAYBACK_SECRET``), valid ``MEDIA_PLAYBACK_TOKEN_TTL``.
2. The HLS playlists (``hls/master.m3u8`` and ``hls/<rung>.m3u8``) take the
   token in the query string, because a native HLS player (Safari) cannot add
   headers. A tampered, expired or foreign token is 401. Every playlist request
   checks access again, so a deleted post, a moderator removal, a block or a
   narrowed audience shows within ``MEDIA_PLAYBACK_ACCESS_CACHE_SECONDS``.
3. Segment URLs in a rendition playlist are presigned per time bucket: the same
   URL for everyone within a bucket (so caches work) that expires at most
   ``MEDIA_HLS_URL_WINDOW_SECONDS`` later. After a removal, playback stops when
   those URLs expire: within that window.

The gunicorn access log (and the web edge) skip ``/hls/`` paths: the token is
in the URL.
"""

from __future__ import annotations

import time

import jwt
from django.conf import settings
from django.core.cache import cache

from tara_common.exceptions import TaraAPIError

from . import post_client, storage, video
from .models import MediaAsset, MediaVariant

AUDIENCE = "media-playback"
PLAYLIST_TYPE = "application/vnd.apple.mpegurl"
SEGMENT_TYPE = "video/mp2t"


def _not_found() -> TaraAPIError:
    return TaraAPIError("Media not found.", code="not_found", http_status_code=404)


def _unauthorized() -> TaraAPIError:
    return TaraAPIError(
        "The playback link is invalid or has expired.", code="unauthenticated", http_status_code=401
    )


# ---- who may watch ------------------------------------------------------------------


def post_visible(viewer_id: str, post_id: str) -> bool:
    """Post's visibility answer for the viewer, cached briefly (fails closed)."""
    key = f"media:vis:{viewer_id}:{post_id}"
    cached = cache.get(key)
    if cached is not None:
        return bool(cached)
    visible = post_client.can_view_post(str(viewer_id), str(post_id))
    cache.set(key, 1 if visible else 0, settings.MEDIA_PLAYBACK_ACCESS_CACHE_SECONDS)
    return visible


def can_watch(viewer_id: str, asset: MediaAsset) -> bool:
    """A transcoded video: its owner, or whoever post says may see its post.

    Unlike photos, the answer always comes from post, even for a public post,
    so a blocked viewer, a removed post and a narrowed audience all apply. A
    video on no post yet (still in the composer) is its owner's only.
    """
    if str(asset.owner_id) == str(viewer_id):
        return True
    return asset.post_id is not None and post_visible(str(viewer_id), str(asset.post_id))


def watchable_asset(viewer_id: str, media_id: str) -> MediaAsset:
    asset = MediaAsset.objects.filter(
        id=media_id, kind=MediaAsset.Kind.VIDEO, deleted_at__isnull=True
    ).first()
    if asset is None or not asset.purpose or not can_watch(viewer_id, asset):
        raise _not_found()
    return asset


# ---- tokens ---------------------------------------------------------------------


def issue_token(viewer_id: str, media_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "aud": AUDIENCE,
            "sub": str(viewer_id),
            "mid": str(media_id),
            "iat": now,
            "exp": now + settings.MEDIA_PLAYBACK_TOKEN_TTL,
        },
        settings.MEDIA_PLAYBACK_SECRET,
        algorithm="HS256",
    )


def viewer_from_token(token: str, media_id: str) -> str:
    """The viewer the token was issued to, for this media only; 401 otherwise."""
    if not token:
        raise _unauthorized()
    try:
        claims = jwt.decode(
            token,
            settings.MEDIA_PLAYBACK_SECRET,
            algorithms=["HS256"],
            audience=AUDIENCE,
            options={"require": ["exp", "sub", "mid"]},
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized() from exc
    if claims.get("mid") != str(media_id):
        raise _unauthorized()
    return str(claims["sub"])


# ---- what the player gets ----------------------------------------------------------


def _poster_url(asset: MediaAsset, variants: list[MediaVariant]) -> str | None:
    poster = next((v for v in variants if v.kind == MediaVariant.Kind.POSTER), None)
    return storage.presign_get(poster.storage_key, content_type="image/jpeg") if poster else None


def playback(viewer_id: str, media_id: str) -> dict:
    asset = watchable_asset(viewer_id, media_id)
    data = _payload(viewer_id, asset)
    if data is None:
        raise _not_found()  # only the owner sees a video before it is ready
    return data


def playback_many(viewer_id: str, media_ids: list[str]) -> list[dict]:
    """``playback`` for several videos at once, in request order. Ids the
    viewer would get a 404 for (unknown, not a transcoded video, not allowed,
    not ready to a non-owner) are left out. Post is asked once per post, and
    its answers are cached as for single requests."""
    wanted = list(dict.fromkeys(str(m) for m in media_ids))
    rows = {
        str(a.id): a
        for a in MediaAsset.objects.filter(
            id__in=wanted, kind=MediaAsset.Kind.VIDEO, deleted_at__isnull=True
        )
        .exclude(purpose="")
        .prefetch_related("variants")
    }
    out = []
    for m in wanted:
        asset = rows.get(m)
        if asset is None or not can_watch(viewer_id, asset):
            continue
        data = _payload(viewer_id, asset)
        if data is not None:
            out.append(data)
    return out


def _payload(viewer_id: str, asset: MediaAsset) -> dict | None:
    """What the player gets for a video the viewer may watch; None when it is
    not ready and the viewer is not its owner."""
    media_id = str(asset.id)
    ready = asset.status == MediaAsset.Status.READY
    if not ready and str(asset.owner_id) != str(viewer_id):
        return None
    data = {
        "id": str(asset.id),
        "status": asset.status,
        "failure_code": asset.failure_code or None,
        "duration_ms": asset.duration_ms,
        "width": asset.width,
        "height": asset.height,
        "hls_url": None,
        "mp4_url": None,
        "poster_url": None,
        "expires_in": settings.MEDIA_PLAYBACK_TOKEN_TTL,
    }
    if not ready:
        return data
    variants = list(asset.variants.all())
    token = issue_token(viewer_id, media_id)
    # Relative to the API root, so the client resolves it against its own API base.
    data["hls_url"] = f"media/{asset.id}/hls/master.m3u8?token={token}"
    data["poster_url"] = _poster_url(asset, variants)
    mp4 = next((v for v in variants if v.kind == MediaVariant.Kind.MP4), None)
    if mp4:
        data["mp4_url"] = storage.presign_get(mp4.storage_key, content_type="video/mp4")
    return data


def _playable(token: str, media_id: str) -> tuple[MediaAsset, str]:
    viewer = viewer_from_token(token, media_id)
    asset = watchable_asset(viewer, media_id)
    if asset.status != MediaAsset.Status.READY:
        raise _not_found()
    return asset, viewer


def _renditions(asset: MediaAsset) -> list[MediaVariant]:
    return sorted(asset.variants.filter(kind=MediaVariant.Kind.HLS), key=lambda v: v.height or 0)


def rung_of(variant: MediaVariant) -> int:
    return min(variant.width or 0, variant.height or 0)


def master_playlist(token: str, media_id: str) -> str:
    asset, _ = _playable(token, media_id)
    has_audio = bool((asset.video_meta.get("probe") or {}).get("has_audio"))
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS"]
    for v in _renditions(asset):
        rung = rung_of(v)
        lines.append(
            f"#EXT-X-STREAM-INF:BANDWIDTH={max(v.bitrate or 0, 1)},"
            f"RESOLUTION={v.width}x{v.height},"
            f'CODECS="{video.codecs(rung, has_audio)}"'
        )
        lines.append(f"{rung}.m3u8?token={token}")
    return "\n".join(lines) + "\n"


def segment_window(now: float | None = None) -> tuple[int, int]:
    """(signed_at, expires): the start of the current half-window bucket, and a
    lifetime ending one full window after it, so a URL is valid for between
    half a window and a window, and identical for every request in the bucket."""
    window = max(2, settings.MEDIA_HLS_URL_WINDOW_SECONDS)
    bucket = window // 2
    now = int(now if now is not None else time.time())
    return now - now % bucket, window


def rendition_playlist(token: str, media_id: str, rung: int) -> str:
    asset, _ = _playable(token, media_id)
    variant = next((v for v in _renditions(asset) if rung_of(v) == rung), None)
    if variant is None:
        raise _not_found()
    signed_at, expires = segment_window()
    out = []
    for line in variant.manifest.splitlines():
        if line and not line.startswith("#"):
            if not video.SEGMENT_NAME.match(line):
                continue  # only the segments the transcoder wrote
            line = storage.presign_get_at(
                f"{variant.storage_key}/{line}",
                signed_at=signed_at,
                expires=expires,
                content_type=SEGMENT_TYPE,
            )
        out.append(line)
    return "\n".join(out) + "\n"
