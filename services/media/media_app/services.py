"""Media business logic: signed uploads, completion, authorized access."""

from __future__ import annotations

import logging
import unicodedata
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import events, post_client, storage, validation
from .models import MediaAsset, MediaVariant, UploadSession

logger = logging.getLogger("tara.media.services")


def sign_upload(owner_id: str, *, kind: str, mime: str, size: int, visibility: str) -> dict:
    if kind not in MediaAsset.Kind.values:
        raise TaraAPIError("Unsupported media kind.", code="validation_error", http_status_code=400)
    if not validation.is_allowed(kind, mime):
        raise TaraAPIError(
            "This file type is not allowed.", code="validation_error", http_status_code=400
        )
    mime = validation.normalize_mime(mime)
    if size > settings.MAX_UPLOAD_BYTES:
        raise TaraAPIError(
            "File exceeds the size limit.", code="validation_error", http_status_code=400
        )
    if visibility not in MediaAsset.Visibility.values:
        visibility = MediaAsset.Visibility.PUBLIC

    asset = MediaAsset(owner_id=owner_id, kind=kind, mime=mime, bytes=size, visibility=visibility)
    asset.storage_key = f"{kind}/{owner_id}/{asset.id}"
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
    if stored.size > settings.MAX_UPLOAD_BYTES:
        raise _reject(asset, source_key, "File exceeds the size limit.")
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
    with transaction.atomic():
        asset.status = MediaAsset.Status.PROCESSING
        asset.bytes = size
        asset.etag = etag
        asset.save(update_fields=["status", "bytes", "etag", "updated_at"])
        events.emit(
            "media.uploaded",
            subject_id=str(asset.id),
            payload={"owner": str(owner_id), "kind": asset.kind, "bytes": asset.bytes},
            actor_id=str(owner_id),
        )

        def _enqueue() -> None:
            from .tasks import process_media

            process_media.delay(str(asset.id))

        transaction.on_commit(_enqueue)
    return asset


# ---- access ----------------------------------------------------------------------


def _can_view(viewer_id: str, asset: MediaAsset) -> bool:
    if str(asset.owner_id) == str(viewer_id):
        return True
    if asset.restricted:
        # Attached to a non-public post: the post decides, and fails closed.
        return asset.post_id is not None and post_client.can_view_post(
            str(viewer_id), str(asset.post_id)
        )
    return asset.visibility == MediaAsset.Visibility.PUBLIC


def get_asset_for_viewer(viewer_id: str, media_id: str) -> MediaAsset:
    asset = MediaAsset.objects.filter(id=media_id, deleted_at__isnull=True).first()
    if asset is None or not _can_view(viewer_id, asset):
        # Don't reveal private media existence.
        raise TaraAPIError("Media not found.", code="not_found", http_status_code=404)
    return asset


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


def asset_url(asset: MediaAsset, *, filename: str = "") -> str:
    """The presigned GET URL of the asset's original, with its verified type."""
    if asset.kind in INLINE_KINDS:
        return storage.presign_get(asset.storage_key, content_type=asset.mime)
    return storage.presign_get(
        asset.storage_key,
        content_type=asset.mime or "application/octet-stream",
        disposition=attachment_disposition(download_filename(asset, filename)),
    )


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
    if with_urls:
        data["url"] = (
            asset_url(asset, filename=filename) if asset.status == MediaAsset.Status.READY else None
        )
        for v in asset.variants.all():
            data["variants"].append(
                {
                    "kind": v.kind,
                    # Variants are made here: thumbnails are JPEG.
                    "url": storage.presign_get(
                        v.storage_key,
                        content_type="image/jpeg" if v.kind == MediaVariant.Kind.THUMB else "",
                    ),
                    "width": v.width,
                    "height": v.height,
                    "duration_ms": v.duration_ms,
                }
            )
    return data


def download_url(viewer_id: str, media_id: str) -> str:
    asset = get_asset_for_viewer(viewer_id, media_id)
    if asset.status != MediaAsset.Status.READY:
        raise TaraAPIError("Media is not ready.", code="conflict", http_status_code=409)
    return asset_url(asset)


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
        }
        for a in assets
    ]


def bind_to_post(owner_id: str, post_id: str, media_ids: list[str], *, restricted: bool) -> dict:
    """Attach the owner's media to a post, restricted to its audience or not.

    Post calls this before it commits the post, so the media are already
    restricted when the post becomes visible. A repeat call for the same post
    can only tighten: it never lifts a restriction. Narrowing an audience then
    always takes effect, and a late or reordered call for an older, wider
    audience cannot reopen the media; post's visibility check already lets
    the wider audience in.

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
    attached_elsewhere: set[str] = set()
    with transaction.atomic():
        assets = list(MediaAsset.objects.select_for_update().filter(id__in=media_ids, **live))
        for asset in assets:
            current = str(asset.post_id) if asset.post_id else None
            if current == str(post_id):
                asset.restricted = asset.restricted or restricted
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
