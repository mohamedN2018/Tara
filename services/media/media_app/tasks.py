"""Async media processing.

Images are cleaned first: EXIF (including GPS), XMP and comments are removed
and the EXIF orientation is applied, and the clean copy replaces the stored
upload. Only then are thumbnails made and the asset marked ready, so nobody is
ever served the original (no URL is issued before READY). Video transcoding
and audio waveforms are not implemented. If processing fails, the original is
kept but never served, and `media.failed` lets owners show a retry state
(brief §8). A storage outage is retried (``RETRY_BACKOFF``) before that.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import events, imaging, storage
from .models import MediaAsset, MediaVariant, UploadSession

logger = logging.getLogger("tara.media.tasks")

THUMB_SIZE = 320
RETRY_BACKOFF = 30  # seconds, doubled for each retry
# S3 answers that mean "try again later", not "this file is bad".
_TRANSIENT_S3_CODES = {"SlowDown", "RequestTimeout", "ServiceUnavailable", "InternalError"}


def is_transient(exc: Exception) -> bool:
    """A storage outage (connection, timeout, 5xx), as opposed to a bad file."""
    from botocore.exceptions import BotoCoreError, ClientError

    if isinstance(exc, ConnectionError | TimeoutError | BotoCoreError):
        return True
    if isinstance(exc, ClientError):
        error = getattr(exc, "response", {}) or {}
        status = int(error.get("ResponseMetadata", {}).get("HTTPStatusCode") or 0)
        return status >= 500 or error.get("Error", {}).get("Code") in _TRANSIENT_S3_CODES
    return False


@shared_task(name="media.process_media", bind=True, max_retries=3, ignore_result=True)
def process_media(self, media_id: str) -> None:
    asset = MediaAsset.objects.filter(id=media_id).first()
    if asset is None or asset.status != MediaAsset.Status.PROCESSING:
        return
    try:
        clean_image(asset)
        # Saved now, so a retry after a later outage re-cleans the clean copy
        # as what it is (a HEIC upload is a JPEG from here on).
        asset.save(update_fields=["bytes", "etag", "mime", "updated_at"])
        variants = derive_variants(asset)
        with transaction.atomic():
            asset.status = MediaAsset.Status.READY
            asset.scan_status = "clean"  # virus-scan integration hook
            asset.save(
                update_fields=["status", "scan_status", "bytes", "etag", "mime", "updated_at"]
            )
            events.emit(
                "media.processed",
                subject_id=str(asset.id),
                payload={
                    "owner": str(asset.owner_id),
                    "kind": asset.kind,
                    "variants": [v[0] for v in variants],
                },
                actor_id=str(asset.owner_id),
            )
    except Exception as exc:  # noqa: BLE001 - preserve original, signal retry state
        retries = self.request.retries or 0
        if is_transient(exc) and retries < self.max_retries:
            logger.warning("media processing hit a storage outage; retrying", exc_info=True)
            raise self.retry(exc=exc, countdown=RETRY_BACKOFF * 2**retries) from exc
        logger.exception("media processing failed", extra={"media_id": media_id})
        with transaction.atomic():
            asset.status = MediaAsset.Status.FAILED
            asset.error = str(exc)[:500]
            asset.save(update_fields=["status", "error", "updated_at"])
            events.emit(
                "media.failed",
                subject_id=str(asset.id),
                payload={"owner": str(asset.owner_id), "retryable": True},
                actor_id=str(asset.owner_id),
            )


def clean_image(asset: MediaAsset) -> None:
    """Replace the stored image with a metadata-free copy; set its size, ETag
    and type (a HEIC upload is stored as JPEG).

    Only sets the fields; the caller saves them.
    """
    if asset.kind != MediaAsset.Kind.IMAGE or settings.STORAGE_BACKEND == "fake":
        return
    mime = imaging.stored_mime(asset.mime)
    clean = imaging.sanitize_image(storage.read(asset.storage_key), asset.mime)
    etag = storage.write(asset.storage_key, clean, mime)
    if not etag:  # every S3 PUT returns one; never leave the row looking unprocessed
        found = storage.stat(asset.storage_key, 1)
        etag = found.etag if found else ""
    asset.etag = etag
    asset.bytes = len(clean)
    asset.mime = mime


def derive_variants(asset: MediaAsset) -> list[tuple[str, str, dict]]:
    """Write the thumbnail of an image and make sure its variant row exists.

    Video and audio are served as uploaded for now.
    """
    if asset.kind != MediaAsset.Kind.IMAGE:
        return []
    key = f"{asset.storage_key}/thumb.jpg"
    if settings.STORAGE_BACKEND != "fake":
        storage.write(key, _thumbnail(storage.read(asset.storage_key)), "image/jpeg")
    variants = [(MediaVariant.Kind.THUMB, key, {"width": THUMB_SIZE, "height": THUMB_SIZE})]
    for kind, variant_key, meta in variants:
        MediaVariant.objects.get_or_create(
            media=asset, kind=kind, defaults={"storage_key": variant_key, **meta}
        )
    return variants


def _thumbnail(content: bytes) -> bytes:
    return imaging.thumbnail(content, THUMB_SIZE)


# A client may still complete an upload whose URL expired just after its PUT.
UPLOAD_GRACE = timedelta(hours=1)
EXPIRE_BATCH = 500


@shared_task(name="media.expire_stale_uploads", ignore_result=True)
def expire_stale_uploads() -> int:
    """Fail uploads never completed (an hour past their URL) and delete their staging object.

    Locks the asset, then the session, in the order completion does, and skips
    any session a completion has claimed meanwhile. Storage is called after
    commit; a failed delete is left to the bucket's staging expiry rule.
    """
    cutoff = timezone.now() - UPLOAD_GRACE
    stale = list(
        UploadSession.objects.filter(
            completed_at__isnull=True,
            expires_at__lt=cutoff,
            media__status=MediaAsset.Status.UPLOADING,
        )
        .order_by("expires_at")
        .values_list("pk", "media_id")[:EXPIRE_BATCH]
    )
    expired = 0
    for session_pk, media_id in stale:
        with transaction.atomic():
            asset = (
                MediaAsset.objects.select_for_update()
                .filter(pk=media_id, status=MediaAsset.Status.UPLOADING)
                .first()
            )
            session = (
                UploadSession.objects.select_for_update()
                .filter(pk=session_pk, completed_at__isnull=True)
                .first()
            )
            if asset is None or session is None:
                continue
            asset.status = MediaAsset.Status.FAILED
            asset.error = "The upload expired."
            asset.save(update_fields=["status", "error", "updated_at"])
        expired += 1
        if session.staging_key and settings.STORAGE_BACKEND != "fake":
            try:
                storage.delete(session.staging_key)
            except Exception:  # noqa: BLE001 - the bucket rule removes it later
                logger.warning("could not delete a stale upload", extra={"media_id": str(media_id)})
    return expired
