"""Ranking session v2 (02 section 22; WP 4.10).

A ranked first page stores the whole ranked list in ``redis-hot`` so later pages
read their slice and never shift or repeat. v2 changes three things against v1
(``feed/ranking.py`` before phase 4, which packed ``FeedItem.id`` as 32 hex chars):

1. each item is **24 bytes of binary**: 16 for the post id, 1 for the candidate
   source, 1 for the reason, 6 for the top three factor codes with their quantized
   contributions (``explain``). 1,050 items take 25,200 bytes;
2. **one key per surface**: ``feed:rank:{surface}:{viewer}`` (``intel.hot``), so
   Home, Reels, Video, Groups and Discover never overwrite each other; the cursor
   names its surface;
3. later pages are re-checked: connection items are reloaded from ``FeedItem`` by
   ``(recipient, post_id)``, other items from ``intel_content_ref``, and the page runs
   E1 to E5 (plus E1b, E1c, E6b) again (``eligibility.recheck``), so content deleted,
   hidden, blocked or muted since the first page is not returned.

Per-impression scores are **not** stored here: they ride in the serve token.
"""

from __future__ import annotations

import logging
import struct
import uuid
from dataclasses import dataclass

from .. import hot
from . import explain

logger = logging.getLogger("tara.intel.session")

VERSION = 2
ITEM_BYTES = 24
# Wire codes: append only, never reorder.
SOURCES = (
    "",
    "connections",
    "follow_pull",
    "groups",
    "reels",
    "video",
    "discovery",
    "trending",
    "new_creators",
)
REASONS = (
    "",
    "self",
    "friend",
    "follow",
    "page",
    "group",
    "group_notify",
    "capped",
    "new_follow",
    "public",
    "discovery",
)
_FACTOR = struct.Struct(">BbBbBb")


@dataclass(frozen=True)
class Entry:
    post_id: str
    source: str
    reason: str
    factors: tuple[tuple[int, int], ...] = ()


def _code(table: tuple[str, ...], value: str) -> int:
    try:
        return table.index(value or "")
    except ValueError:
        return 0  # unknown: stored as "none", never guessed


def pack(entries) -> bytes:
    out = bytearray()
    for e in entries:
        f = list(e.factors)[:3] + [(0, 0)] * (3 - min(len(e.factors), 3))
        out += uuid.UUID(str(e.post_id)).bytes
        out += bytes([_code(SOURCES, e.source), _code(REASONS, e.reason)])
        out += _FACTOR.pack(f[0][0], f[0][1], f[1][0], f[1][1], f[2][0], f[2][1])
    return bytes(out)


def unpack(raw: bytes, start: int = 0, stop: int | None = None) -> list[Entry]:
    n = len(raw) // ITEM_BYTES
    stop = n if stop is None else min(stop, n)
    out = []
    for i in range(max(start, 0), stop):
        chunk = raw[i * ITEM_BYTES : (i + 1) * ITEM_BYTES]
        a, b, c, d, e, f = _FACTOR.unpack(chunk[18:24])
        factors = tuple((code, q) for code, q in ((a, b), (c, d), (e, f)) if code)
        out.append(
            Entry(
                str(uuid.UUID(bytes=chunk[:16])),
                SOURCES[chunk[16]] if chunk[16] < len(SOURCES) else "",
                REASONS[chunk[17]] if chunk[17] < len(REASONS) else "",
                factors,
            )
        )
    return out


def key(surface: str, viewer_id) -> str:
    if surface not in hot.RANK_SURFACES:
        raise KeyError(f"no ranking session for surface {surface!r}")
    return f"feed:rank:{surface}:{viewer_id}"


def save(surface: str, viewer_id, session: dict, ttl: int, cache=None) -> bool:
    """One session per (surface, viewer); a new first page replaces it. False when
    redis-hot refused (the page is served as a latest-order fallback)."""
    try:
        (cache or hot.hot()).set(key(surface, viewer_id), {**session, "v": VERSION}, timeout=ttl)
        return True
    except Exception:  # noqa: BLE001 - a full or down redis-hot only costs the ranking
        logger.warning("ranking session not stored; latest fallback", exc_info=True)
        return False


def load(surface: str, viewer_id, sid: str, cache=None) -> dict | None:
    try:
        session = (cache or hot.hot()).get(key(surface, viewer_id))
    except Exception:  # noqa: BLE001
        logger.warning("ranking session unreadable; latest fallback", exc_info=True)
        return None
    if not isinstance(session, dict) or session.get("v") != VERSION or session.get("sid") != sid:
        return None
    return session


def contains(surface: str, viewer_id, post_id, cache=None) -> Entry | None:
    """The entry of ``post_id`` in the viewer's current session of ``surface``."""
    try:
        session = (cache or hot.hot()).get(key(surface, viewer_id))
    except Exception:  # noqa: BLE001 - redis-hot down: nothing can be proven from it
        return None
    if not isinstance(session, dict) or session.get("v") != VERSION:
        return None
    wanted = uuid.UUID(str(post_id)).bytes
    raw = session.get("items") or b""
    for i in range(len(raw) // ITEM_BYTES):
        if raw[i * ITEM_BYTES : i * ITEM_BYTES + 16] == wanted:
            return unpack(raw, i, i + 1)[0]
    return None


def factor_names(entry: Entry) -> list[tuple[str, float]]:
    return explain.visible(list(entry.factors))
