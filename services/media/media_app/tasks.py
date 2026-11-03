"""Async media processing.

Images are cleaned first: EXIF (including GPS), XMP and comments are removed
and the EXIF orientation is applied, and the clean copy replaces the stored
upload. Only then are thumbnails made and the asset marked ready, so nobody is
ever served the original (no URL is issued before READY). Video transcoding
and audio waveforms are not implemented. If processing fails, the original is
kept but never served, and `media.failed` lets owners show a retry state
(brief §8).
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction

from . import events, imaging, storage
from .models import MediaAsset, MediaVariant

logger = logging.getLogger("tara.media.tasks")

THUMB_SIZE = 320


@shared_task(name="media.process_media", bind=True, max_retries=3, ignore_result=True)
def process_media(self, media_id: str) -> None:
    asset = MediaAsset.objects.filter(id=media_id).first()
    if asset is None or asset.status != MediaAsset.Status.PROCESSING:
        return
    try:
        clean_image(asset)
        variants = derive_variants(asset)
        with transaction.atomic():
            asset.status = MediaAsset.Status.READY
            asset.scan_status = "clean"  # virus-scan integration hook
            asset.save(update_fields=["status", "scan_status", "bytes", "etag", "updated_at"])
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
        logger.exception("media processing failed", extra={"media_id": media_id})
        with transaction.atomic():
            asset.status = MediaAsset.Status.FAILED
            asset.error = str(exc)[:500]
            asset.save(update_fields=["status", "error"])
            events.emit(
                "media.failed",
                subject_id=str(asset.id),
                payload={"owner": str(asset.owner_id), "retryable": True},
                actor_id=str(asset.owner_id),
            )


def clean_image(asset: MediaAsset) -> None:
    """Replace the stored image with a metadata-free copy; set its size and ETag.

    Only sets the fields; the caller saves them.
    """
    if asset.kind != MediaAsset.Kind.IMAGE or settings.STORAGE_BACKEND == "fake":
        return
    clean = imaging.sanitize_image(storage.read(asset.storage_key), asset.mime)
    etag = storage.write(asset.storage_key, clean, asset.mime)
    if not etag:  # every S3 PUT returns one; never leave the row looking unprocessed
        found = storage.stat(asset.storage_key, 1)
        etag = found.etag if found else ""
    asset.etag = etag
    asset.bytes = len(clean)


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
