"""Remove EXIF/GPS from images that became ready before images were cleaned.

Since milestone 1.5, processing cleans every image (EXIF and GPS, XMP,
comments; orientation applied) before it is READY, and records the stored
object's ETag. Images that were READY before that are still the original
upload, metadata included, and are served that way. Their ETag column is empty
(it was added with the cleaning), so that is what this command selects. For
each it cleans the stored object exactly as processing does, rewrites the
thumbnail, and saves the new size and ETag, which also marks it done: a second
run finds nothing. It is safe to interrupt and re-run.

Run it once after deploying media, next to post's ``restrict_post_media``:

    python manage.py sanitize_existing_images [--dry-run] [--batch 100] [--hide-failed]

An image that cannot be cleaned (object missing, storage down, undecodable,
over the size limits) is reported and left as it is, so a re-run retries it.
``--hide-failed`` marks those FAILED instead, so they are never served again.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ... import tasks
from ...models import MediaAsset


class Command(BaseCommand):
    help = "Clean EXIF/GPS from images that were ready before cleaning (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--hide-failed",
            action="store_true",
            help="Mark images that cannot be cleaned FAILED, so they are no longer served.",
        )

    def handle(self, *args, **options):
        if settings.STORAGE_BACKEND == "fake":
            raise CommandError("needs real object storage (TARA_STORAGE_BACKEND=s3)")
        size, dry_run, hide_failed = options["batch"], options["dry_run"], options["hide_failed"]
        legacy = MediaAsset.objects.filter(
            kind=MediaAsset.Kind.IMAGE,
            status=MediaAsset.Status.READY,
            deleted_at__isnull=True,
            etag="",
        ).order_by("id")
        cleaned = failed = 0
        last_id = None
        while True:
            page = legacy.filter(id__gt=last_id) if last_id else legacy
            batch = list(page[:size])
            if not batch:
                break
            for asset in batch:
                if dry_run:
                    cleaned += 1
                    continue
                if self._clean(asset, hide_failed):
                    cleaned += 1
                else:
                    failed += 1
            last_id = batch[-1].id
        verb = "would clean" if dry_run else "cleaned"
        self.stdout.write(f"{verb} {cleaned} images; {failed} failed")

    def _clean(self, asset: MediaAsset, hide_failed: bool) -> bool:
        try:
            tasks.clean_image(asset)
            tasks.derive_variants(asset)
        except Exception as exc:  # noqa: BLE001 - report it and go on with the rest
            self.stderr.write(f"media {asset.id}: {type(exc).__name__}: {str(exc)[:200]}")
            if hide_failed:
                MediaAsset.objects.filter(id=asset.id, etag="").update(
                    status=MediaAsset.Status.FAILED,
                    error=f"not cleaned: {str(exc)[:450]}",
                    updated_at=timezone.now(),
                )
            return False
        # Saved per image, so an interrupted run keeps what it did. The etag=""
        # guard keeps a concurrent run from writing over a newer result.
        MediaAsset.objects.filter(id=asset.id, etag="").update(
            bytes=asset.bytes, etag=asset.etag, updated_at=timezone.now()
        )
        return True
