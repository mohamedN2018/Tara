"""Media business logic: signed uploads, completion, authorized access."""

from __future__ import annotations

import logging
import time
import unicodedata
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import events, playback, post_client, storage, validation
from .models import MediaAsset, MediaVariant, UploadSession

logger = logging.getLogger("tara.media.services")


def is_transcoded(asset: MediaAsset) -> bool:
    """A video the transcoder turns into HLS (a ``purpose`` is set), as opposed
    to one served as uploaded (chat)."""
    return asset.kind == MediaAsset.Kind.VIDEO and bool(asset.purpose)


def max_upload_bytes(asset: MediaAsset) -> int:
    if is_transcoded(asset):
        return int(settings.MEDIA_VIDEO_PURPOSES[asset.purpose]["max_bytes"])
    return settings.MAX_UPLOAD_BYTES


def _lock_video_quota(owner_id: str) -> None:
    """Serialize video quota checks per account until the transaction ends.

    Locking the account's existing rows is not enough under READ COMMITTED: a
    waiter never sees the row the holder inserted, and with no rows nothing is
    locked at all. An advisory lock on the account is the serialization point;
    the count is then a separate statement, so it sees rows committed by
    earlier holders. (A hash collision only serializes two accounts.)"""
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", [f"media-video-quota:{owner_id}"]
        )


def _check_video_quota(owner_id: str, size: int) -> None:
    """At most MEDIA_VIDEO_DAILY_UPLOADS transcoded videos, and
    MEDIA_VIDEO_DAILY_BYTES declared bytes, per account in 24 hours.

    Call inside the transaction that saves the new row: the account's lock is
    held until it commits, so parallel requests cannot both take the last
    slot. Completion refuses a video larger than declared, so the declared
    bytes bound what is stored."""
    _lock_video_quota(owner_id)
    since = timezone.now() - timedelta(hours=24)
    recent = list(
        MediaAsset.objects.filter(
            owner_id=owner_id, kind=MediaAsset.Kind.VIDEO, created_at__gte=since
        )
        .exclude(purpose="")
        .values_list("bytes", flat=True)
    )
    if (
        len(recent) >= settings.MEDIA_VIDEO_DAILY_UPLOADS
        or sum(recent) + size > settings.MEDIA_VIDEO_DAILY_BYTES
    ):
        raise TaraAPIError(
            "You reached today's video upload limit; try again tomorrow.",
            code="video_quota_exceeded",
            http_status_code=429,
        )


def sign_upload(
    owner_id: str, *, kind: str, mime: str, size: int, visibility: str, purpose: str = ""
) -> dict:
    if kind not in MediaAsset.Kind.values:
        raise TaraAPIError("Unsupported media kind.", code="validation_error", http_status_code=400)
    if purpose and (kind != MediaAsset.Kind.VIDEO or purpose not in settings.MEDIA_VIDEO_PURPOSES):
        raise TaraAPIError(
            "Unsupported media purpose.", code="validation_error", http_status_code=400
        )
    if not validation.is_allowed(kind, mime, purpose):
        raise TaraAPIError(
            "This file type is not allowed.", code="validation_error", http_status_code=400
        )
    mime = validation.normalize_mime(mime)
    if visibility not in MediaAsset.Visibility.values:
        visibility = MediaAsset.Visibility.PUBLIC
    asset = MediaAsset(
        owner_id=owner_id,
        kind=kind,
        mime=mime,
        bytes=size,
        visibility=visibility,
        purpose=purpose,
    )
    if size > max_upload_bytes(asset):
        raise TaraAPIError(
            "File exceeds the size limit.",
            code="video_too_large" if purpose else "validation_error",
            http_status_code=400,
        )
    # Transcoded videos live under their own prefix: the transcoder's storage
    # user can reach ``videos/`` and nothing else (no photos, no chat files).
    prefix = "videos" if is_transcoded(asset) else kind
    asset.storage_key = f"{prefix}/{owner_id}/{asset.id}"
    with transaction.atomic():
        if is_transcoded(asset):
            _check_video_quota(owner_id, size)
        asset.save()
    # The browser writes to a staging key; only complete() writes the real key.
    session = UploadSession.objects.create(
        media=asset,
        staging_key=f"staging/{asset.storage_key}",
        expires_at=timezone.now() + timedelta(seconds=settings.SIGNED_URL_TTL),
    )
    return {
        "media_id": str(asset.id),
        "storage_key": asset.storage_key,
        "upload_url": storage.presign_put(session.staging_key, mime),
        "method": "PUT",
        "expires_in": settings.SIGNED_URL_TTL,
    }


# ---- completion ----------------------------------------------------------------


def _claim_upload(owner_id: str, media_id: str) -> UploadSession:
    """Mark the session used. A session completes once; a second call is 409."""
    with transaction.atomic():
        asset = (
            MediaAsset.objects.select_for_update()
            .filter(id=media_id, owner_id=owner_id, deleted_at__isnull=True)
            .first()
        )
        if asset is None:
            raise TaraAPIError("Media not found.", code="not_found", http_status_code=404)
        session = UploadSession.objects.select_for_update().filter(media=asset).first()
        if (
            session is None
            or session.completed_at is not None
            or asset.status != MediaAsset.Status.UPLOADING
        ):
            raise Conflict("This upload was already completed.", code="upload_already_completed")
        session.completed_at = timezone.now()
        session.save(update_fields=["completed_at"])
    session.media = asset
    return session


def _release_claim(session: UploadSession) -> None:
    """Let the client retry after a storage outage (not after a rejected file)."""
    UploadSession.objects.filter(pk=session.pk).update(completed_at=None)


def _reject(asset: MediaAsset, source_key: str, problem: str) -> TaraAPIError:
    try:
        storage.delete(source_key)
    except Exception:  # noqa: BLE001 - the rejection matters more than the cleanup
        logger.warning("could not delete a rejected upload", extra={"media_id": str(asset.id)})
    MediaAsset.objects.filter(pk=asset.pk).update(
        status=MediaAsset.Status.FAILED, error=problem, updated_at=timezone.now()
    )
    return TaraAPIError(problem, code="validation_error", http_status_code=400)


def _verify_and_store(asset: MediaAsset, source_key: str) -> tuple[int, str]:
    """Check what actually arrived (the presigned PUT limits neither size nor
    content), then copy exactly that version to the asset's key.

    Returns the real size and ETag. Raises 400 (and fails the asset) for a bad
    file; storage errors propagate.
    """
    try:
        stored = storage.stat(source_key, validation.HEAD_BYTES)
    except storage.ObjectChanged:
        raise _reject(asset, source_key, "The upload changed while it was checked.") from None
    if stored is None:
        raise _reject(asset, source_key, "The upload was not found.")
    if stored.size > max_upload_bytes(asset):
        raise _reject(asset, source_key, "File exceeds the size limit.")
    if is_transcoded(asset) and stored.size > asset.bytes:
        # The daily byte quota was charged the declared size at signing.
        raise _reject(asset, source_key, "The upload is larger than its declared size.")
    if not validation.matches_signature(asset.mime, stored.head):
        raise _reject(asset, source_key, "The file content does not match its type.")
    if source_key == asset.storage_key:  # a session signed before staging keys
        return stored.size, stored.etag
    try:
        etag = storage.copy(source_key, asset.storage_key, if_match=stored.etag)
    except storage.ObjectChanged:
        raise _reject(asset, source_key, "The upload changed while it was checked.") from None
    storage.delete(source_key)
    return stored.size, etag


def complete_upload(owner_id: str, media_id: str) -> MediaAsset:
    session = _claim_upload(owner_id, media_id)
    asset = session.media
    size, etag = asset.bytes, ""
    if settings.STORAGE_BACKEND != "fake":
        try:
            size, etag = _verify_and_store(asset, session.staging_key or asset.storage_key)
        except TaraAPIError:
            raise
        except Exception as exc:  # noqa: BLE001 - storage outage: retryable
            logger.warning("upload verification failed", exc_info=True)
            _release_claim(session)
            raise TaraAPIError(
                "Storage is unavailable; try again.",
                code="dependency_unavailable",
                http_status_code=503,
            ) from exc
    transcoded = is_transcoded(asset)
    with transaction.atomic():
        # A transcoded video waits for the transcoder ("uploaded"); the rest is
        # processed by the media worker.
        asset.status = MediaAsset.Status.UPLOADED if transcoded else MediaAsset.Status.PROCESSING
        asset.bytes = size
        asset.etag = etag
        asset.save(update_fields=["status", "bytes", "etag", "updated_at"])
        payload = {"owner": str(owner_id), "kind": asset.kind, "bytes": asset.bytes}
        if asset.purpose:
            payload["purpose"] = asset.purpose
        events.emit(
            "media.uploaded", subject_id=str(asset.id), payload=payload, actor_id=str(owner_id)
        )

        def _enqueue() -> None:
            if transcoded:
                from .transcode import prepare

                prepare.delay(str(asset.id))
                return
            from .tasks import process_media

            process_media.delay(str(asset.id))

        transaction.on_commit(_enqueue)
    return asset


# ---- access ----------------------------------------------------------------------


def _can_view(viewer_id: str, asset: MediaAsset, post_check=None) -> bool:
    """``post_check(post_id)`` answers for restricted photos; the default asks
    post each time (a batch passes a per-request memo of the same answer)."""
    if is_transcoded(asset):
        return playback.can_watch(viewer_id, asset)
    if str(asset.owner_id) == str(viewer_id):
        return True
    if asset.restricted:
        # Attached to a non-public post: the post decides, and fails closed.
        if asset.post_id is None:
            return False
        if post_check is not None:
            return post_check(str(asset.post_id))
        return post_client.can_view_post(str(viewer_id), str(asset.post_id))
    return asset.visibility == MediaAsset.Visibility.PUBLIC


def get_asset_for_viewer(viewer_id: str, media_id: str) -> MediaAsset:
    asset = MediaAsset.objects.filter(id=media_id, deleted_at__isnull=True).first()
    if asset is None or not _can_view(viewer_id, asset):
        # Don't reveal private media existence.
        raise TaraAPIError("Media not found.", code="not_found", http_status_code=404)
    return asset


def assets_for_viewer(viewer_id: str, media_ids: list[str]) -> list[MediaAsset]:
    """The assets of ``media_ids`` the viewer may see, by the detail endpoint's
    rules, in request order. Unknown, deleted and forbidden ids are left out,
    so the answer reveals no more than one 404 per id would.

    Post is asked once per restricted post in the batch, not once per photo."""
    wanted = list(dict.fromkeys(str(m) for m in media_ids))
    rows = {
        str(a.id): a
        for a in MediaAsset.objects.filter(id__in=wanted, deleted_at__isnull=True).prefetch_related(
            "variants"
        )
    }
    answers: dict[str, bool] = {}

    def post_check(post_id: str) -> bool:
        if post_id not in answers:
            answers[post_id] = post_client.can_view_post(str(viewer_id), post_id)
        return answers[post_id]

    return [rows[m] for m in wanted if m in rows and _can_view(viewer_id, rows[m], post_check)]


# Shown in place in the app. Everything else (PDFs, audio files) is served as a
# download, so it never renders as a page of the storage origin.
INLINE_KINDS = frozenset({MediaAsset.Kind.IMAGE, MediaAsset.Kind.VIDEO})
_EXTENSIONS = {
    "application/pdf": "pdf",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/webm": "webm",
    "audio/wav": "wav",
}
MAX_FILENAME = 120


def download_filename(asset: MediaAsset, requested: str = "") -> str:
    """``requested`` made safe to put in a header, with the extension of the
    asset's real type; the asset id when nothing usable is left.

    Path parts, control and format characters (bidi overrides included, so a
    name cannot display as ``...fdp.exe``) and surrounding dots go.
    """
    ext = _EXTENSIONS.get(asset.mime, "bin")
    name = unicodedata.normalize("NFC", requested or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if unicodedata.category(c)[0] not in ("C", "Z") or c == " ")
    stem = name.strip().strip(".").rsplit(".", 1)[0].strip()
    stem = stem[: MAX_FILENAME - len(ext) - 1].strip() or str(asset.id)
    return f"{stem}.{ext}"


def attachment_disposition(filename: str) -> str:
    """``Content-Disposition: attachment`` with an ASCII fallback and the UTF-8
    name (RFC 6266 / 5987), so Arabic names survive."""
    fallback = "".join(c for c in filename if 32 <= ord(c) < 127 and c not in '"\\;%')
    if fallback.rsplit(".", 1)[0].strip(" ._-") == "":
        fallback = "download." + filename.rsplit(".", 1)[-1]
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _signed_url(asset: MediaAsset, filename: str, now: float) -> tuple[str | None, int | None]:
    """``(url, expires_at)`` of the asset's original, with its verified type.

    An image is shown in place: a bucketed, cacheable URL (WP 4c.5-B3). Chat video
    keeps a per-request URL, and a file of any other kind is a download
    (``Content-Disposition: attachment``). None for a transcoded video: its
    original is never served (5.2); players get the renditions through ``playback``."""
    if is_transcoded(asset):
        return None, None
    if asset.kind == MediaAsset.Kind.IMAGE:
        return storage.presign_display(asset.storage_key, content_type=asset.mime, now=now)
    expires_at = int(now) + settings.SIGNED_URL_TTL
    if asset.kind in INLINE_KINDS:
        return storage.presign_get(asset.storage_key, content_type=asset.mime), expires_at
    url = storage.presign_get(
        asset.storage_key,
        content_type=asset.mime or "application/octet-stream",
        disposition=attachment_disposition(download_filename(asset, filename)),
    )
    return url, expires_at


def asset_url(asset: MediaAsset, *, filename: str = "") -> str | None:
    """The presigned GET URL of the asset's original (see ``_signed_url``)."""
    return _signed_url(asset, filename, time.time())[0]


def variant_url(v: MediaVariant, now: float) -> tuple[str, int]:
    """``(url, expires_at)`` of a variant: bucketed for what is shown in place
    (``DISPLAY_VARIANTS``), per request for the rest (the MP4 fallback)."""
    content_type = _VARIANT_TYPES.get(v.kind, "")
    if v.kind in DISPLAY_VARIANTS:
        return storage.presign_display(v.storage_key, content_type=content_type, now=now)
    url = storage.presign_get(v.storage_key, content_type=content_type)
    return url, int(now) + settings.SIGNED_URL_TTL


def asset_payload(asset: MediaAsset, *, with_urls: bool = True, filename: str = "") -> dict:
    data = {
        "id": str(asset.id),
        "kind": asset.kind,
        "status": asset.status,
        "mime": asset.mime,
        "bytes": asset.bytes,
        "visibility": asset.visibility,
        "variants": [],
    }
    if is_transcoded(asset):
        data.update(
            {
                "purpose": asset.purpose,
                "failure_code": asset.failure_code or None,
                "duration_ms": asset.duration_ms,
                "width": asset.width,
                "height": asset.height,
            }
        )
    elif asset.kind == MediaAsset.Kind.IMAGE and asset.width and asset.height:
        # The real size as displayed (WP 4c.5-B3), so the client reserves the space.
        data.update({"width": asset.width, "height": asset.height})
    if with_urls:
        now = time.time()
        expiries = []
        data["url"] = None
        if asset.status == MediaAsset.Status.READY:
            data["url"], expires_at = _signed_url(asset, filename, now)
            if expires_at is not None:
                expiries.append(expires_at)
        # HLS rows are segment prefixes, played through the token-checked playlists.
        variants = sorted(
            (v for v in asset.variants.all() if v.kind != MediaVariant.Kind.HLS),
            key=lambda v: _VARIANT_ORDER.get(v.kind, len(_VARIANT_ORDER)),
        )
        for v in variants:
            url, expires_at = variant_url(v, now)
            expiries.append(expires_at)
            data["variants"].append(
                {
                    "kind": v.kind,
                    "url": url,
                    "width": v.width,
                    "height": v.height,
                    "duration_ms": v.duration_ms,
                }
            )
        # Epoch seconds: the earliest expiry of the URLs above, so a client caches
        # them exactly as long as they work (null when there are none).
        data["urls_expire_at"] = min(expiries) if expiries else None
    return data


# Variants are made here: thumbnails and posters are JPEG, display sizes WebP.
_VARIANT_TYPES = {
    MediaVariant.Kind.THUMB: "image/jpeg",
    MediaVariant.Kind.DISPLAY_640: "image/webp",
    MediaVariant.Kind.DISPLAY_1280: "image/webp",
    MediaVariant.Kind.POSTER: "image/jpeg",
    MediaVariant.Kind.POSTER_480: "image/jpeg",
    MediaVariant.Kind.MP4: "video/mp4",
}
# Shown in place: signed per bucket, cacheable (WP 4c.5-B3, 4c.6-B3).
DISPLAY_VARIANTS = frozenset(
    {
        MediaVariant.Kind.THUMB,
        MediaVariant.Kind.DISPLAY_640,
        MediaVariant.Kind.DISPLAY_1280,
        MediaVariant.Kind.POSTER,
        MediaVariant.Kind.POSTER_480,
    }
)
# The order variants are listed in (the smallest still first).
_VARIANT_ORDER = {
    kind: i
    for i, kind in enumerate(
        (
            MediaVariant.Kind.THUMB,
            MediaVariant.Kind.DISPLAY_640,
            MediaVariant.Kind.DISPLAY_1280,
            MediaVariant.Kind.POSTER,
            MediaVariant.Kind.POSTER_480,
            MediaVariant.Kind.MP4,
        )
    )
}


def download_url(viewer_id: str, media_id: str) -> str:
    asset = get_asset_for_viewer(viewer_id, media_id)
    if asset.status != MediaAsset.Status.READY:
        raise TaraAPIError("Media is not ready.", code="conflict", http_status_code=409)
    url = asset_url(asset)
    if url is None:  # a transcoded video: no original to download
        raise TaraAPIError("Media not found.", code="not_found", http_status_code=404)
    return url


# ---- internal: post attachment ------------------------------------------------------


def internal_lookup(media_ids: list[str]) -> list[dict]:
    """What another service needs to validate attachments. No URLs."""
    assets = MediaAsset.objects.filter(id__in=media_ids, deleted_at__isnull=True)
    return [
        {
            "id": str(a.id),
            "owner_id": str(a.owner_id),
            "kind": a.kind,
            "status": a.status,
            "mime": a.mime,
            "bytes": a.bytes,
            "visibility": a.visibility,
            "restricted": a.restricted,
            "post_id": str(a.post_id) if a.post_id else None,
            # Video pipeline (5.2): "" for media served as uploaded.
            "purpose": a.purpose,
            "failure_code": a.failure_code or None,
            "duration_ms": a.duration_ms,
            # As displayed (rotation applied): post's reel rules (5.5) read them.
            "width": a.width,
            "height": a.height,
        }
        for a in assets
    ]


def bind_to_post(owner_id: str, post_id: str, media_ids: list[str], *, restricted: bool) -> dict:
    """Attach the owner's media to a post, restricted to its audience or not.

    Post calls this before it commits the post, so the media are already
    restricted when the post becomes visible. A repeat call for the same post
    tightens at once. It lifts a restriction (a draft published as public)
    only when post says the post is public right now, and only for media no
    other call touched since post was asked. So narrowing an audience always
    takes effect, and a late or reordered call for an older, wider audience
    cannot reopen the media.

    One media belongs to one post. Media already bound to another post move
    only when post says that post is not live (a post that failed after
    binding, or a deleted one); otherwise, or when post cannot answer, they
    are skipped and listed in ``attached_elsewhere``. Media of another owner,
    or deleted, are skipped. Post is asked before any row is locked; call this
    outside a transaction.
    """
    media_ids = [str(m) for m in media_ids]
    live = {"owner_id": owner_id, "deleted_at__isnull": True}
    elsewhere = {
        str(p)
        for p in MediaAsset.objects.filter(id__in=media_ids, post_id__isnull=False, **live)
        .exclude(post_id=post_id)
        .values_list("post_id", flat=True)
        .distinct()
    }
    # False only when post answered that the old post is not visible to its own author.
    released = {p for p in elsewhere if post_client.post_is_live(owner_id, p) is False}
    # Lifting asks post first; a tightening saved after ``asked_at`` wins.
    asked_at = timezone.now()
    lift = (
        not restricted
        and MediaAsset.objects.filter(
            id__in=media_ids, post_id=post_id, restricted=True, **live
        ).exists()
        and post_client.post_is_public(str(post_id)) is True
    )
    attached_elsewhere: set[str] = set()
    with transaction.atomic():
        assets = list(MediaAsset.objects.select_for_update().filter(id__in=media_ids, **live))
        for asset in assets:
            current = str(asset.post_id) if asset.post_id else None
            if current == str(post_id):
                if restricted:
                    asset.restricted = True
                elif asset.restricted and lift and asset.updated_at <= asked_at:
                    asset.restricted = False
            elif current is None or current in released:
                asset.post_id = post_id
                asset.restricted = restricted
            else:
                attached_elsewhere.add(str(asset.id))
                continue
            asset.save(update_fields=["post_id", "restricted", "updated_at"])
    bound = {str(a.id) for a in assets} - attached_elsewhere
    return {
        "bound": sorted(bound),
        "skipped": sorted(set(media_ids) - bound),
        "attached_elsewhere": sorted(attached_elsewhere),
    }
