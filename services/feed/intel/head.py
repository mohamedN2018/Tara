"""Repeat-exposure metrics of Home first pages (07 WP 4b.11, early).

On every ranked Home first page, the ids of the page are compared with the
viewer's previous first page, kept in ``feed:head:home:{viewer}`` (raw key, ids
only: 16 bytes per post, TTL ``head.ttl_s``):

- ``intel_first_page_overlap``: the Jaccard of the two pages (histogram);
- ``intel_repeat_display_total``: how many items were on the previous page too.

Nothing is stored for a viewer with ``personalization_off`` (owner decision 24), nor
under a config version without the ``head`` block (``home@1``, ``home@2``). A refused
write (``noeviction``) is counted in ``intel_hot_write_failed_total{key="head"}``
and never fails the page. The per-session column ``intel_feed_session.head_overlap``
is R3's, not this module's.
"""

from __future__ import annotations

import uuid

from . import hot, metrics, preferences, repetition
from .config import SurfaceConfig

ID_BYTES = 16


def _pack(post_ids) -> bytes:
    return b"".join(uuid.UUID(str(p)).bytes for p in post_ids)


def _unpack(raw: bytes) -> list[str]:
    n = len(raw) // ID_BYTES
    return [str(uuid.UUID(bytes=raw[i * ID_BYTES : (i + 1) * ID_BYTES])) for i in range(n)]


def record(viewer_id, surface: str, post_ids: list[str], cfg: SurfaceConfig) -> float | None:
    """Observe the overlap with the previous head, then store this one. Returns the
    Jaccard, or None when nothing was compared (first page ever, off, no block)."""
    if "head" not in cfg.params or not post_ids:
        return None
    if preferences.personalization_off(viewer_id):
        return None
    name = hot.head_key(surface, viewer_id)
    previous = hot.raw_get(name)
    overlap = None
    if previous:
        before = _unpack(previous)
        overlap = repetition.jaccard(before, post_ids)
        metrics.first_page_overlap(overlap)
        metrics.repeat_display(len(set(before) & set(post_ids)))
    hot.raw_set(name, _pack(post_ids), cfg.get("head.ttl_s"), "head")
    return overlap
