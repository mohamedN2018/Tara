"""Media business logic: signed uploads, completion, authorized access."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tara_common.exceptions import TaraAPIError

from . import events, storage
from .models import MediaAsset, UploadSession


def sign_upload(owner_id: str, *, kind: str, mime: str, size: int, visibility: str) -> dict:
    if kind not in MediaAsset.Kind.values:
        raise TaraAPIError("Unsupported media kind.", code="validation_error", http_status_code=400)
    if size > settings.MAX_UPLOAD_BYTES:
        raise TaraAPIError(
            "File exceeds the size limit.", code="validation_error", http_status_code=400
        )
    if visibility not in MediaAsset.Visibility.values:
        visibility = MediaAsset.Visibility.PUBLIC

    asset = MediaAsset(owner_id=owner_id, kind=kind, mime=mime, bytes=size, visibility=visibility)
    asset.storage_key = f"{kind}/{owner_id}/{asset.id}"
    asset.save()
    UploadSession.objects.create(
        media=asset, expires_at=timezone.now() + timedelta(seconds=settings.SIGNED_URL_TTL)
    )
    return {
        "media_id": str(asset.id),
        "storage_key": asset.storage_key,
        "upload_url": storage.presign_put(asset.storage_key, mime),
        "method": "PUT",
        "expires_in": settings.SIGNED_URL_TTL,
    }


def complete_upload(owner_id: str, media_id: str) -> MediaAsset:
    asset = MediaAsset.objects.filter(id=media_id, owner_id=owner_id).first()
    if asset is None:
        raise TaraAPIError("Media not found.", code="not_found", http_status_code=404)
    if asset.status != MediaAsset.Status.UPLOADING:
        return asset  # idempotent
    with transaction.atomic():
        asset.status = MediaAsset.Status.PROCESSING
        asset.save(update_fields=["status"])
        UploadSession.objects.filter(media=asset).update(completed_at=timezone.now())
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


def _can_view(viewer_id: str, asset: MediaAsset) -> bool:
    if str(asset.owner_id) == str(viewer_id):
        return True
    return asset.visibility == MediaAsset.Visibility.PUBLIC


def get_asset_for_viewer(viewer_id: str, media_id: str) -> MediaAsset:
    asset = MediaAsset.objects.filter(id=media_id, deleted_at__isnull=True).first()
    if asset is None or not _can_view(viewer_id, asset):
        # Don't reveal private media existence.
        raise TaraAPIError("Media not found.", code="not_found", http_status_code=404)
    return asset


def asset_payload(asset: MediaAsset, *, with_urls: bool = True) -> dict:
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
            storage.presign_get(asset.storage_key)
            if asset.status == MediaAsset.Status.READY
            else None
        )
        for v in asset.variants.all():
            data["variants"].append(
                {
                    "kind": v.kind,
                    "url": storage.presign_get(v.storage_key),
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
    return storage.presign_get(asset.storage_key)
