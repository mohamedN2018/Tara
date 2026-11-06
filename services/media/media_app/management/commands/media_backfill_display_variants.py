"""Give existing media their display sizes (Tara Intelligence WP 4c.5-B3, 4c.6-B3).

    python manage.py media_backfill_display_variants [--batch 100] [--limit N] [--dry-run]

- A ready image gets its real ``width``/``height`` and the WebP ``display_640`` /
  ``display_1280`` copies its size reaches (never upscaled; none for a GIF, which
  may be animated). New uploads get them from ``process_media``.
- A thumbnail row written before the real sizes were recorded says 320 x 320
  whatever the image; its real size is read from the thumbnail object (the
  object itself is not rewritten), so a client's ``srcset`` never states a
  width the file does not have.
- A ready transcoded video gets ``poster_480`` from its existing ``poster.jpg``
  (a resize, no re-transcode), when the poster reaches a 480 px short side.

It only adds variant objects and rows and fills null sizes: the original and the
existing variants are never deleted or rewritten, and nothing else is written (no
event, no analytics row), so seeded and real media are treated alike without
mixing anything into analytics. Idempotent: an asset that already has what its
size allows is skipped, so a second run does nothing. Chunked by ``--batch`` in id
order; ``--limit`` stops after that many assets were looked at.
"""

from __future__ import annotations

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from media_app import imaging, storage, tasks, transcode
from media_app.models import MediaAsset, MediaVariant

logger = logging.getLogger("tara.media.backfill")

# GIFs may be animated: a still display copy would stop the animation.
NO_DISPLAY_MIMES = frozenset({"image/gif"})


def thumb_needs_size(asset: MediaAsset, variants: list[MediaVariant]) -> bool:
    """A thumbnail row still carrying the old placeholder size (320 x 320) for an
    image whose real thumbnail cannot be that size (not square, or smaller)."""
    thumb = next((v for v in variants if v.kind == MediaVariant.Kind.THUMB), None)
    if thumb is None or (thumb.width, thumb.height) != (tasks.THUMB_SIZE, tasks.THUMB_SIZE):
        return False
    if not (asset.width and asset.height):
        return True
    longest, shortest = max(asset.width, asset.height), min(asset.width, asset.height)
    # A real 320 x 320 thumbnail needs a (near) square image of at least 320 px.
    return longest < tasks.THUMB_SIZE or round(shortest * tasks.THUMB_SIZE / longest) < (
        tasks.THUMB_SIZE
    )


def image_done(asset: MediaAsset, kinds: set[str], variants: list[MediaVariant] = ()) -> bool:
    if not (asset.width and asset.height):
        return False
    if thumb_needs_size(asset, list(variants)):
        return False
    if asset.mime in NO_DISPLAY_MIMES:
        return True
    longest = max(asset.width, asset.height)
    return all(kind in kinds for kind, side in tasks.DISPLAY_SIZES if side <= longest)


def video_done(variants: list[MediaVariant]) -> bool:
    kinds = {v.kind for v in variants}
    if MediaVariant.Kind.POSTER_480 in kinds:
        return True
    poster = next((v for v in variants if v.kind == MediaVariant.Kind.POSTER), None)
    if poster is None:
        return True  # nothing to resize
    if poster.width and poster.height:
        return min(poster.width, poster.height) < transcode.POSTER_480_SIDE
    return False


class Command(BaseCommand):
    help = "Add display sizes and real image sizes to existing ready media."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=100)
        parser.add_argument("--limit", type=int, default=0, help="0: every asset")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if settings.STORAGE_BACKEND == "fake":
            raise CommandError("the fake storage backend holds no objects")
        batch, limit, dry = max(1, options["batch"]), max(0, options["limit"]), options["dry_run"]
        started = time.monotonic()
        stats = {"seen": 0, "images": 0, "videos": 0, "variants": 0, "skipped": 0, "failed": 0}
        ready = MediaAsset.objects.filter(
            status=MediaAsset.Status.READY, deleted_at__isnull=True
        ).filter(Q(kind=MediaAsset.Kind.IMAGE) | (Q(kind=MediaAsset.Kind.VIDEO) & ~Q(purpose="")))
        last = None
        while not limit or stats["seen"] < limit:
            page = ready.order_by("id")
            if last is not None:
                page = page.filter(id__gt=last)
            size = batch if not limit else min(batch, limit - stats["seen"])
            assets = list(page.prefetch_related("variants")[:size])
            if not assets:
                break
            for asset in assets:
                stats["seen"] += 1
                self._one(asset, dry, stats)
            last = assets[-1].id
        stats["seconds"] = round(time.monotonic() - started, 1)
        verb = "would process" if dry else "processed"
        self.stdout.write(
            f"{verb} {stats['images']} images and {stats['videos']} videos"
            f" ({stats['variants']} variants written); {stats['skipped']} already done;"
            f" {stats['failed']} failed; {stats['seen']} looked at in {stats['seconds']} s"
        )
        return None

    def _one(self, asset: MediaAsset, dry: bool, stats: dict) -> None:
        variants = list(asset.variants.all())
        is_image = asset.kind == MediaAsset.Kind.IMAGE
        done = (
            image_done(asset, {v.kind for v in variants}, variants)
            if is_image
            else video_done(variants)
        )
        if done:
            stats["skipped"] += 1
            return
        stats["images" if is_image else "videos"] += 1
        if dry:
            return
        try:
            stats["variants"] += (
                self._image(asset, variants) if is_image else self._video(asset, variants)
            )
        except Exception as exc:  # noqa: BLE001 - one bad object never stops the run
            stats["failed"] += 1
            stats["images" if is_image else "videos"] -= 1
            logger.warning(
                "display backfill failed",
                extra={"media_id": str(asset.id), "error": type(exc).__name__},
            )

    @staticmethod
    def _image(asset: MediaAsset, variants: list[MediaVariant]) -> int:
        # The real size of the thumbnail, from the object (read, never rewritten).
        thumb = next((v for v in variants if v.kind == MediaVariant.Kind.THUMB), None)
        if thumb is not None and thumb_needs_size(asset, variants):
            width, height, _ = imaging.dimensions(storage.read(thumb.storage_key))
            MediaVariant.objects.filter(pk=thumb.pk).update(width=width, height=height)
            if image_done(asset, {v.kind for v in variants}):
                return 0  # only the thumbnail row was out of date
        source = storage.read(asset.storage_key)
        if asset.mime in NO_DISPLAY_MIMES:
            made = []
            width, height, _ = imaging.dimensions(source)
            if (asset.width, asset.height) != (width, height):
                MediaAsset.objects.filter(pk=asset.pk).update(width=width, height=height)
        else:
            made = tasks.display_variants(asset, source)
        for kind, key, meta in made:
            MediaVariant.objects.update_or_create(
                media=asset, kind=kind, defaults={"storage_key": key, **meta}
            )
        return len(made)

    @staticmethod
    def _video(asset: MediaAsset, variants: list[MediaVariant]) -> int:
        poster = next(v for v in variants if v.kind == MediaVariant.Kind.POSTER)
        small = transcode.poster_480(asset, storage.read(poster.storage_key))
        if small is None:
            return 0
        MediaVariant.objects.update_or_create(
            media=asset, kind=MediaVariant.Kind.POSTER_480, defaults=small
        )
        return 1
