"""Async media processing.

PLACEHOLDER PIPELINE: real transcoding/thumbnailing/waveform extraction is a
later phase. This task records the variant rows and marks the asset ready so the
end-to-end flow (upload -> process -> ready -> media.processed) works. If
processing fails, the original is preserved and `media.failed` lets owners show
a retry state (brief §8).
"""

from __future__ import annotations

import logging

from celery import shared_task

from . import events
from .models import MediaAsset, MediaVariant

logger = logging.getLogger("tara.media.tasks")


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
    base = asset.storage_key
    if asset.kind in (MediaAsset.Kind.IMAGE, MediaAsset.Kind.VIDEO):
        out = [(MediaVariant.Kind.THUMB, f"{base}/thumb.jpg", {"width": 320, "height": 320})]
        if asset.kind == MediaAsset.Kind.VIDEO:
            out.append((MediaVariant.Kind.TRANSCODE, f"{base}/720p.mp4", {"duration_ms": 0}))
        return out
    if asset.kind in (MediaAsset.Kind.AUDIO, MediaAsset.Kind.VOICE):
        return [(MediaVariant.Kind.WAVEFORM, f"{base}/waveform.json", {"duration_ms": 0})]
    return []
