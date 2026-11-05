"""The reels reconcile job (roadmap 5.5).

A reel lives in post, its video in media. They can drift apart: the owner
deletes the video in media, a re-transcode fails, or the bind that attached the
video to the reel's post never landed (media was down after post committed).
This job asks media about the videos of live reels, oldest-checked first, and:

- video gone in media -> ``media_missing``: the reel leaves the reels surfaces;
- video failed -> ``media_failed``: the same;
- video bound to another post -> ``media_elsewhere``: the same;
- video unbound -> bound again to the reel's post, restricted unless the post
  is public and visible; if media refuses, the reel is hidden as above;
- video ready on this post again -> back to ``published``.

Hiding is a ``publish_state`` change, never a delete, so a mistake (or media
recovering) is repaired by the next run. Every change records one
``reel.state.changed`` (ids and states only) in the same transaction as the
update (Tara Intelligence WP 2.6, D15); a dry run records nothing. Media
down: the run stops and changes nothing more; the next tick carries on.
Idempotent and safe beside another run.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from posts import events, media_client
from posts.models import Audience

from tara_common.exceptions import TaraAPIError

from .models import PublishState, Reel

logger = logging.getLogger("tara.post.reels.reconcile")

LOOKUP_BATCH = 100  # media's batch limit
DEFAULT_LIMIT = 500  # reels looked at per run


def _state_for(reel: Reel, info) -> str | None:
    """The state media's answer calls for, or ``None`` when the video needs a rebind."""
    if info is None:
        return PublishState.MEDIA_MISSING
    if info.status == "failed":
        return PublishState.MEDIA_FAILED
    if info.post_id is None:
        return None
    if str(info.post_id) != str(reel.post_id):
        return PublishState.MEDIA_ELSEWHERE
    return PublishState.PUBLISHED


def _rebind(reel: Reel, info) -> str:
    post = reel.post
    restricted = post.audience != Audience.PUBLIC or not post.is_visible
    result = media_client.bind(
        info.owner_id, str(post.id), [str(reel.media_id)], restricted=restricted
    )
    if result.attached_elsewhere:
        return PublishState.MEDIA_ELSEWHERE
    if result.skipped:
        return PublishState.MEDIA_MISSING
    return PublishState.PUBLISHED


def reconcile(*, limit: int = DEFAULT_LIMIT, dry_run: bool = False) -> dict:
    """Check up to ``limit`` reels (never checked first, then the longest ago).

    Returns counts: ``checked``, ``hidden``, ``restored``, ``rebound`` and
    ``stopped`` (True when media was unreachable).
    """
    stats = {"checked": 0, "hidden": 0, "restored": 0, "rebound": 0, "stopped": False}
    reels = list(
        Reel.objects.filter(post__deleted_at__isnull=True)
        .select_related("post")
        .order_by(F("reconciled_at").asc(nulls_first=True), "post_id")[: max(limit, 0)]
    )
    for start in range(0, len(reels), LOOKUP_BATCH):
        chunk = reels[start : start + LOOKUP_BATCH]
        try:
            found = media_client.lookup([str(r.media_id) for r in chunk])
        except TaraAPIError:
            logger.warning("reels reconcile: media unavailable, stopping", exc_info=True)
            stats["stopped"] = True
            return stats
        for reel in chunk:
            info = found.get(str(reel.media_id))
            state = _state_for(reel, info)
            if state is None:
                if dry_run:
                    stats["rebound"] += 1
                    stats["checked"] += 1
                    continue
                try:
                    state = _rebind(reel, info)
                except TaraAPIError:
                    logger.warning("reels reconcile: rebind failed, stopping", exc_info=True)
                    stats["stopped"] = True
                    return stats
                if state == PublishState.PUBLISHED:
                    stats["rebound"] += 1
            stats["checked"] += 1
            if state != reel.publish_state:
                key = "restored" if state == PublishState.PUBLISHED else "hidden"
                stats[key] += 1
                logger.info(
                    "reels reconcile: state changed",
                    extra={"reel_id": str(reel.post_id), "from": reel.publish_state, "to": state},
                )
            if not dry_run:
                _save_state(reel, state)
    return stats


def _save_state(reel: Reel, state: str) -> None:
    """Store the checked state; a change also records ``reel.state.changed``.

    The row is re-read under a lock so a concurrent run that already moved it
    records nothing (exactly one event per change).
    """
    with transaction.atomic():
        current = (
            Reel.objects.select_for_update()
            .filter(pk=reel.pk)
            .values_list("publish_state", flat=True)
            .first()
        )
        if current is None:
            return
        Reel.objects.filter(pk=reel.pk).update(publish_state=state, reconciled_at=timezone.now())
        if current != state:
            events.emit(
                "reel.state.changed",
                subject_id=str(reel.post_id),
                payload={
                    "post_id": str(reel.post_id),
                    "author_id": str(reel.author_id),
                    "from_state": current,
                    "to_state": state,
                },
                actor_id=None,
                partition_key=f"author:{reel.author_id}",
            )
