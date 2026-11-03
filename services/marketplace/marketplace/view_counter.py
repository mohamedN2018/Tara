"""Listing view counter: per-viewer cooldown in Redis, flushed to Postgres by beat.

The cooldown is QTech's ``SET NX EX`` marker (``backend/core/visitors.py``): one
view per viewer per listing per window. Unlike QTech, nothing is written to the
database per hit; counts go to a Redis hash that ``flush`` moves to
``Listing.view_count`` in one transaction.

Flush is crash-safe and exactly-once:
1. the live buffer is RENAMEd to a batch key (atomic; new hits start a new hash);
2. the batch's counts are added in one DB transaction that also records the batch
   id in ``ProcessedEvent``, so a batch can never be applied twice;
3. the batch key is deleted. A batch left behind by a crash between 1 and 3 is
   found by its prefix on the next run and either applied or, if step 2 already
   committed, just deleted.

Counting never breaks a request: if Redis is down the view is simply not counted.
"""

from __future__ import annotations

import logging
import uuid

import redis
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F

from .models import Listing, ProcessedEvent

logger = logging.getLogger(__name__)

FLUSH_CONSUMER = "marketplace.view-flush"
_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            settings.MARKETPLACE_REDIS_URL,
            socket_timeout=0.5,
            socket_connect_timeout=0.5,
            decode_responses=True,
        )
    return _client


def _prefix() -> str:
    return settings.MARKETPLACE_VIEW_KEY_PREFIX


def _buffer_key() -> str:
    return f"{_prefix()}buffer"


def _batch_prefix() -> str:
    return f"{_prefix()}batch:"


def record_view(listing_id: str, viewer_id: str) -> bool:
    """Count one view unless this viewer was counted within the cooldown."""
    try:
        r = _redis()
        marker = f"{_prefix()}cd:{listing_id}:{viewer_id}"
        if not r.set(marker, 1, nx=True, ex=settings.MARKETPLACE_VIEW_COOLDOWN_SECONDS):
            return False
        r.hincrby(_buffer_key(), str(listing_id), 1)
        return True
    except redis.RedisError:
        logger.warning("view not counted: redis unavailable", exc_info=True)
        return False


def pending_views(listing_id: str) -> int:
    """Views buffered but not yet flushed (for tests and diagnostics)."""
    try:
        return int(_redis().hget(_buffer_key(), str(listing_id)) or 0)
    except redis.RedisError:
        return 0


def _apply_batch(r: redis.Redis, key: str) -> int:
    batch_id = key.rsplit(":", 1)[-1]
    try:
        batch_uuid = uuid.UUID(batch_id)
    except ValueError:
        r.delete(key)  # not ours
        return 0
    counts = {lid: int(n) for lid, n in r.hgetall(key).items() if int(n) > 0}
    applied = 0
    try:
        with transaction.atomic():
            ProcessedEvent.objects.create(event_id=batch_uuid, consumer=FLUSH_CONSUMER)
            for listing_id, n in counts.items():
                try:
                    uuid.UUID(listing_id)
                except ValueError:
                    continue
                Listing.objects.filter(id=listing_id).update(view_count=F("view_count") + n)
                applied += n
    except IntegrityError:
        applied = 0  # this batch was applied before a crash; only the key is left
    r.delete(key)
    return applied


def flush() -> int:
    """Move buffered views into ``Listing.view_count``. Returns views applied."""
    try:
        r = _redis()
        leftovers = list(r.scan_iter(match=f"{_batch_prefix()}*", count=100))
        batch = f"{_batch_prefix()}{uuid.uuid4()}"
        try:
            r.rename(_buffer_key(), batch)
            leftovers.append(batch)
        except redis.ResponseError:
            pass  # no views since the last flush
        return sum(_apply_batch(r, key) for key in leftovers)
    except redis.RedisError:
        logger.warning("view flush skipped: redis unavailable", exc_info=True)
        return 0
