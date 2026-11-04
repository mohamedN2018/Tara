"""The video transcoder (roadmap 5.2): one Celery chain per video.

``prepare`` downloads the verified upload, probes it, refuses what is too long,
too big or HDR that cannot be tone-mapped, and makes the poster. It then
starts a chain with one step per HLS rendition (240p to 720p, never
upscaled), the optional progressive MP4, and ``finalize``. One step per
rendition keeps every message short, well under RabbitMQ's consumer timeout
(raised for this queue anyway; the steps ack late).

These tasks run only in the media-transcoder container (queue
``media.transcode``, concurrency 1, minimal environment). Each step works in
its own scratch directory, removed in ``finally``. A step runs at most
``MEDIA_TRANSCODE_MAX_ATTEMPTS`` times (redeliveries and storage retries
included); a bad file fails at once with a code.

``finalize`` marks the video ready and records ``media.processed`` in the
same transaction, under a row lock, so a replayed step publishes nothing more.
The original upload is then deleted (unless ``MEDIA_KEEP_VIDEO_ORIGINALS``):
viewers only ever get the renditions.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from celery import chain, shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from PIL import Image

from . import events, storage, video
from .models import MediaAsset, MediaVariant
from .tasks import RETRY_BACKOFF, is_transient
from .video import Probe, VideoError

logger = logging.getLogger("tara.media.transcode")

_ACTIVE = (MediaAsset.Status.UPLOADED, MediaAsset.Status.PROCESSING)
_STEP = {"bind": True, "acks_late": True, "reject_on_worker_lost": True, "ignore_result": True}
_EXTINF = re.compile(r"^#EXTINF:([0-9.]+)")


def is_transcoded(asset: MediaAsset) -> bool:
    return asset.kind == MediaAsset.Kind.VIDEO and bool(asset.purpose)


def max_seconds(asset: MediaAsset) -> int:
    caps = settings.MEDIA_VIDEO_PURPOSES.get(asset.purpose) or {}
    return int(caps.get("max_seconds") or 60)


def hls_prefix(asset: MediaAsset, rung: int) -> str:
    return f"{asset.storage_key}/hls/{rung}"


@contextmanager
def scratch(media_id: str) -> Iterator[Path]:
    """A private working directory for one step, always removed afterwards."""
    root = Path(settings.MEDIA_TRANSCODE_SCRATCH_DIR)
    root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{media_id}-", dir=root))
    try:
        yield work
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _begin(media_id: str, step: str, task_id: str | None = None) -> MediaAsset | None:
    """Lock the asset, count this attempt; None when there is nothing to do.

    ``prepare`` claims an ``uploaded`` video for its delivery (``task_id``:
    the same across a retry and a redelivery). Another ``prepare`` message
    for the video (a requeue that waited behind the first) is skipped without
    counting a try, and so is any ``prepare`` once the chain was started."""
    with transaction.atomic():
        asset = MediaAsset.objects.select_for_update().filter(id=media_id).first()
        if asset is None or asset.deleted_at is not None or asset.status not in _ACTIVE:
            return None
        meta = dict(asset.video_meta or {})
        if step != "prepare":
            if asset.status != MediaAsset.Status.PROCESSING:
                return None
        elif asset.status == MediaAsset.Status.UPLOADED:
            meta["prepare_task"] = task_id
        elif meta.get("chain_started") or meta.get("prepare_task", task_id) != task_id:
            # (A row claimed before claims were recorded keeps the old behaviour.)
            logger.info("duplicate prepare skipped", extra={"media_id": media_id})
            return None
        tries = dict(meta.get("tries") or {})
        tries[step] = int(tries.get(step, 0)) + 1
        meta["tries"] = tries
        asset.video_meta = meta
        asset.status = MediaAsset.Status.PROCESSING
        asset.save(update_fields=["video_meta", "status", "updated_at"])
    if tries[step] > settings.MEDIA_TRANSCODE_MAX_ATTEMPTS:
        fail(media_id, "too_many_attempts", f"{step} was tried {tries[step] - 1} times")
        return None
    return asset


def _mark_chain_started(pk) -> None:
    with transaction.atomic():
        asset = MediaAsset.objects.select_for_update().filter(pk=pk).first()
        if asset is None:
            return
        meta = dict(asset.video_meta or {})
        meta["chain_started"] = True
        MediaAsset.objects.filter(pk=pk).update(video_meta=meta)


def _source(asset: MediaAsset, work: Path) -> Path:
    src = work / "source"
    storage.download_to(asset.storage_key, src)
    return src


def _run_step(task, media_id: str, step: str, body) -> None:
    """Run ``body(asset)`` for an active asset; bad files fail with their code,
    storage outages are retried, anything else fails as ``internal``."""
    asset = _begin(media_id, step, task.request.id)
    if asset is None:
        return
    try:
        body(asset)
    except VideoError as exc:
        logger.info("video refused", extra={"media_id": media_id, "code": exc.code})
        fail(media_id, exc.code, exc.detail)
    except Exception as exc:  # noqa: BLE001 - every outcome is recorded on the asset
        retries = task.request.retries or 0
        if is_transient(exc) and retries < task.max_retries:
            logger.warning("transcode hit a storage outage; retrying", exc_info=True)
            raise task.retry(exc=exc, countdown=RETRY_BACKOFF * 2**retries) from exc
        logger.exception("transcode step failed", extra={"media_id": media_id, "step": step})
        fail(media_id, "storage_unavailable" if is_transient(exc) else "internal", str(exc))


@shared_task(name="media.video.prepare", max_retries=3, **_STEP)
def prepare(self, media_id: str) -> None:
    def body(asset: MediaAsset) -> None:
        with scratch(media_id) as work:
            src = _source(asset, work)
            probe = video.probe(src, asset.mime)
            video.check_source(probe, max_seconds(asset))
            poster = video.poster(src, asset.mime, probe, work / "poster")
            with Image.open(poster) as img:
                width, height = img.size
            key = f"{asset.storage_key}/poster.jpg"
            storage.upload_from(key, poster, "image/jpeg")
        MediaVariant.objects.update_or_create(
            media=asset,
            kind=MediaVariant.Kind.POSTER,
            defaults={"storage_key": key, "width": width, "height": height},
        )
        rungs = video.ladder(probe)
        meta = dict(MediaAsset.objects.get(pk=asset.pk).video_meta or {})
        meta.update({"probe": probe.as_meta(), "rungs": rungs})
        MediaAsset.objects.filter(pk=asset.pk).update(
            video_meta=meta, duration_ms=int(probe.duration * 1000), updated_at=timezone.now()
        )
        steps = [rendition.si(media_id, rung) for rung in rungs]
        if settings.MEDIA_VIDEO_MP4_FALLBACK:
            steps.append(progressive.si(media_id))
        steps.append(finalize.si(media_id))
        chain(*steps).apply_async()
        # After sending: a crash before this line re-sends (steps are
        # idempotent); a later delivery of any prepare sends nothing more.
        _mark_chain_started(asset.pk)

    _run_step(self, media_id, "prepare", body)


def _bandwidth(manifest: str, sizes: dict[str, int]) -> tuple[int, int]:
    """(peak, average) bits per second over the segments."""
    peak, total_bits, total_seconds, duration = 0, 0, 0.0, 0.0
    for line in manifest.splitlines():
        m = _EXTINF.match(line)
        if m:
            duration = float(m.group(1))
        elif line in sizes and duration > 0:
            bits = sizes[line] * 8
            peak = max(peak, int(bits / duration))
            total_bits += bits
            total_seconds += duration
    return peak, int(total_bits / total_seconds) if total_seconds else peak


@shared_task(name="media.video.rendition", max_retries=3, **_STEP)
def rendition(self, media_id: str, rung: int) -> None:
    def body(asset: MediaAsset) -> None:
        probe = Probe.from_meta(asset.video_meta["probe"])
        prefix = hls_prefix(asset, rung)
        with scratch(media_id) as work:
            src = _source(asset, work)
            out = work / "out"
            manifest = video.hls_rendition(src, asset.mime, probe, rung, out, max_seconds(asset))
            sizes = {}
            for name in video.segment_names(manifest):
                sizes[name] = (out / name).stat().st_size
                storage.upload_from(f"{prefix}/{name}", out / name, "video/mp2t")
        peak, average = _bandwidth(manifest, sizes)
        width, height = video.output_size(probe, rung)
        MediaVariant.objects.update_or_create(
            media=asset,
            kind=MediaVariant.Kind.HLS,
            storage_key=prefix,
            defaults={
                "width": width,
                "height": height,
                "bitrate": peak,
                "duration_ms": int(probe.duration * 1000),
                "manifest": manifest,
            },
        )
        logger.info("rendition ready", extra={"media_id": media_id, "rung": rung, "avg": average})

    _run_step(self, media_id, f"rendition-{rung}", body)


@shared_task(name="media.video.progressive", max_retries=3, **_STEP)
def progressive(self, media_id: str) -> None:
    def body(asset: MediaAsset) -> None:
        probe = Probe.from_meta(asset.video_meta["probe"])
        key = f"{asset.storage_key}/mp4/video.mp4"
        with scratch(media_id) as work:
            src = _source(asset, work)
            target, rung = video.mp4_fallback(
                src, asset.mime, probe, work / "mp4", max_seconds(asset)
            )
            storage.upload_from(key, target, "video/mp4")
        width, height = video.output_size(probe, rung)
        MediaVariant.objects.update_or_create(
            media=asset,
            kind=MediaVariant.Kind.MP4,
            defaults={
                "storage_key": key,
                "width": width,
                "height": height,
                "duration_ms": int(probe.duration * 1000),
            },
        )

    _run_step(self, media_id, "progressive", body)


@shared_task(name="media.video.finalize", max_retries=3, **_STEP)
def finalize(self, media_id: str) -> None:
    """Mark the video ready and record ``media.processed``, exactly once."""
    with transaction.atomic():
        asset = MediaAsset.objects.select_for_update().filter(id=media_id).first()
        if asset is None or asset.status != MediaAsset.Status.PROCESSING:
            return  # failed, or already finalized by an earlier delivery
        variants = list(asset.variants.all())
        hls = sorted(
            (v for v in variants if v.kind == MediaVariant.Kind.HLS), key=lambda v: v.height or 0
        )
        expected = set(asset.video_meta.get("rungs") or [])
        made = {min(v.width or 0, v.height or 0) for v in hls}
        if not hls or not expected <= made:
            transaction.on_commit(
                lambda: fail(media_id, "transcode_failed", "a rendition is missing")
            )
            return
        top = hls[-1]
        asset.width, asset.height = top.width, top.height
        asset.status = MediaAsset.Status.READY
        asset.scan_status = "clean"  # virus-scan integration hook
        asset.failure_code = ""
        asset.error = ""
        asset.save(
            update_fields=[
                "width",
                "height",
                "status",
                "scan_status",
                "failure_code",
                "error",
                "updated_at",
            ]
        )
        events.emit(
            "media.processed",
            subject_id=str(asset.id),
            payload={
                "owner": str(asset.owner_id),
                "kind": asset.kind,
                "purpose": asset.purpose,
                "variants": sorted({v.kind for v in variants}),
                "renditions": [min(v.width or 0, v.height or 0) for v in hls],
                "duration_ms": asset.duration_ms,
                "width": asset.width,
                "height": asset.height,
            },
            actor_id=str(asset.owner_id),
        )
    if not settings.MEDIA_KEEP_VIDEO_ORIGINALS:
        _drop_original(asset)


def _drop_original(asset: MediaAsset) -> None:
    try:
        storage.delete(asset.storage_key)
    except Exception:  # noqa: BLE001 - never served; a later run may retry the delete
        logger.warning("could not delete a video original", extra={"media_id": str(asset.id)})
        return
    MediaAsset.objects.filter(pk=asset.pk).update(original_deleted=True)


def fail(media_id: str, code: str, detail: str = "") -> None:
    """Fail the video with ``code``, record ``media.failed`` once, and remove
    what was made (and the original, unless originals are kept)."""
    with transaction.atomic():
        asset = MediaAsset.objects.select_for_update().filter(id=media_id).first()
        if asset is None or asset.status not in _ACTIVE:
            return
        asset.status = MediaAsset.Status.FAILED
        asset.failure_code = code[:32]
        asset.error = (detail or code)[:500]
        asset.save(update_fields=["status", "failure_code", "error", "updated_at"])
        asset.variants.all().delete()
        events.emit(
            "media.failed",
            subject_id=str(asset.id),
            payload={
                "owner": str(asset.owner_id),
                "kind": asset.kind,
                "purpose": asset.purpose,
                "code": asset.failure_code,
                "retryable": False,
            },
            actor_id=str(asset.owner_id),
        )
    try:
        storage.delete_prefix(f"{asset.storage_key}/")
        if not settings.MEDIA_KEEP_VIDEO_ORIGINALS:
            _drop_original(asset)
    except Exception:  # noqa: BLE001 - nothing of a failed video is ever served
        logger.warning("could not clean up a failed video", extra={"media_id": media_id})


# A video verified but never picked up (a lost message, a transcoder outage).
STALLED_AFTER = timedelta(minutes=30)


@shared_task(name="media.requeue_stalled_videos", ignore_result=True)
def requeue_stalled_videos() -> int:
    """Send videos stuck in ``uploaded`` back to the transcoder.

    The first message may only be waiting in a backed-up queue, so a resend
    must never cost the video a try: whichever ``prepare`` arrives first
    claims the video and the others are skipped (``_begin``). A resend also
    expires before the next one is due (``queued_at`` records it), so an
    outage does not pile up one more message per video every run."""
    now = timezone.now()
    stalled = list(
        MediaAsset.objects.filter(
            status=MediaAsset.Status.UPLOADED,
            deleted_at__isnull=True,
            updated_at__lt=now - STALLED_AFTER,
        ).values_list("id", "video_meta")[:100]
    )
    for media_id, meta in stalled:
        meta = dict(meta or {})
        meta["queued_at"] = now.isoformat()
        # Only while still uploaded: a prepare that claimed it meanwhile wins.
        if MediaAsset.objects.filter(pk=media_id, status=MediaAsset.Status.UPLOADED).update(
            video_meta=meta, updated_at=now
        ):
            prepare.apply_async((str(media_id),), expires=now + STALLED_AFTER)
    return len(stalled)
