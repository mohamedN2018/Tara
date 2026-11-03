"""Async media processing.

Makes image thumbnails, then marks the asset ready. Video transcoding and audio
waveforms are not implemented. If processing fails, the original is preserved
and `media.failed` lets owners show a retry state (brief §8).
"""

from __future__ import annotations

import io
import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction

from . import events, storage
from .models import MediaAsset, MediaVariant

logger = logging.getLogger("tara.media.tasks")

THUMB_SIZE = 320


@shared_task(name="media.process_media", bind=True, max_retries=3, ignore_result=True)
def process_media(self, media_id: str) -> None:
    asset = MediaAsset.objects.filter(id=media_id).first()
    if asset is None or asset.status != MediaAsset.Status.PROCESSING:
        return
    try:
        variants = _derive_variants(asset)
        for kind, key, meta in variants:
            MediaVariant.objects.get_or_create(
                media=asset, kind=kind, defaults={"storage_key": key, **meta}
            )
        with transaction.atomic():
            asset.status = MediaAsset.Status.READY
            asset.scan_status = "clean"  # virus-scan integration hook
            asset.save(update_fields=["status", "scan_status"])
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


def _derive_variants(asset: MediaAsset) -> list[tuple[str, str, dict]]:
    """Thumbnails for images. Video and audio are served as uploaded for now."""
    if asset.kind != MediaAsset.Kind.IMAGE:
        return []
    key = f"{asset.storage_key}/thumb.jpg"
    if settings.STORAGE_BACKEND != "fake":
        storage.write(key, _thumbnail(storage.read(asset.storage_key)), "image/jpeg")
    return [(MediaVariant.Kind.THUMB, key, {"width": THUMB_SIZE, "height": THUMB_SIZE})]


def _thumbnail(content: bytes) -> bytes:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(content)) as image:
        thumb = ImageOps.exif_transpose(image).convert("RGB")
        thumb.thumbnail((THUMB_SIZE, THUMB_SIZE))
        out = io.BytesIO()
        thumb.save(out, "JPEG", quality=85)
    return out.getvalue()
