"""Telemetry validation constants and per-event rules (02 sections 8.4 and 12.2).

These numbers define *what is stored*, not how anything is ranked, so they are code
constants with a version stamp rather than ranking-config parameters (02 section
8.4): changing one is a code change reviewed like a migration.
"""

from __future__ import annotations

from datetime import timedelta

from ..models import EventType, ItemType

VALIDATOR_VERSION = 1

MAX_EVENTS_PER_BATCH = 50
MAX_BATCH_BYTES = 32 * 1024
BATCHES_PER_MINUTE = 60  # throttle scope ``intel_signals`` (settings.py)
TS_WINDOW = timedelta(hours=24)
REWATCH_CAP = 3
# Until intel_media_ref (WP 3.1) gives each item its duration, watch time is
# clamped to the longest video media accepts (MEDIA_VIDEO_MAX_SECONDS_POST, 600 s)
# times the rewatch cap.
MAX_MEDIA_DURATION_MS = 600_000
WALL_CLOCK_WINDOW = timedelta(seconds=60)
WALL_CLOCK_TOLERANCE = 1.10
COMPLETE_MIN_FRACTION = 0.9
SKIP_MAX_MS = 2_000
SKIP_MAX_FRACTION = 0.2
REEL_VIEW_MIN_MS = 1_000
MAX_POSITION = 10_000
MAX_PLAY_INDEX = 1_000

POST_KINDS = frozenset({ItemType.POST, ItemType.REEL, ItemType.VIDEO})
VIDEO_KINDS = frozenset({ItemType.POST, ItemType.REEL, ItemType.VIDEO})

# Item types each client event may name.
ITEM_TYPES_FOR = {
    EventType.FEED_IMPRESSION: POST_KINDS,
    EventType.POST_OPEN: POST_KINDS,
    EventType.VIDEO_START: VIDEO_KINDS,
    EventType.VIDEO_PROGRESS: VIDEO_KINDS,
    EventType.VIDEO_COMPLETE: VIDEO_KINDS,
    EventType.VIDEO_REWATCH: VIDEO_KINDS,
    EventType.VIDEO_SKIP: VIDEO_KINDS,
    EventType.REEL_VIEW: frozenset({ItemType.REEL}),
    EventType.PROFILE_VISIT: frozenset({ItemType.PROFILE, ItemType.PAGE}),
}

# Fields each client event must carry (besides id, t, item, ts).
REQUIRED = {
    # ``pos`` is optional: a ranked surface's position comes from the serve token,
    # and a card seen off a ranked surface (a profile, a group, search) has none.
    EventType.FEED_IMPRESSION: (),
    EventType.POST_OPEN: (),
    EventType.VIDEO_START: ("play_index",),
    EventType.VIDEO_PROGRESS: ("watch_ms", "pos_ms"),
    EventType.VIDEO_COMPLETE: ("watch_ms",),
    EventType.VIDEO_REWATCH: ("play_index",),
    EventType.VIDEO_SKIP: ("watch_ms",),
    EventType.REEL_VIEW: ("watch_ms",),
    EventType.PROFILE_VISIT: (),
}

# Events whose ``watch_ms`` is the cumulative watch time of one play
# (item, play_index); the increase over the play's previous value is the time
# the event claims, checked against the wall clock.
WATCH_EVENTS = frozenset(
    {
        EventType.VIDEO_PROGRESS,
        EventType.VIDEO_COMPLETE,
        EventType.VIDEO_SKIP,
        EventType.REEL_VIEW,
    }
)
VIDEO_STATE_EVENTS = WATCH_EVENTS | {EventType.VIDEO_START, EventType.VIDEO_REWATCH}

# A surface hint is used only for an item opened outside a ranked surface.
UNATTRIBUTED_SURFACE_HINTS = frozenset({"profile", "search", "groups", "link"})


class Reject(Exception):
    """One event is dropped; ``reason`` labels ``intel_signal_rejected_total``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def watch_ceiling_ms(duration_ms: int | None) -> int:
    base = duration_ms if duration_ms and duration_ms > 0 else MAX_MEDIA_DURATION_MS
    return base * REWATCH_CAP


def impression_def_max() -> int:
    """The newest impression rule a client may claim: the active Home config's
    ``delivery.impression.def_version`` (read without copying the params)."""
    from ..config import store

    return int(store.resolve("home")[1]["delivery"]["impression"]["def_version"])


def check_shape(event: dict, *, idef_max: int | None = None) -> None:
    """Type, item kind, required fields and per-type value rules.

    A ``feed_impression`` gets ``impression_def``: its ``idef`` when it is within 1
    and ``idef_max`` (default: ``impression_def_max()``), else the event is dropped
    (``invalid_idef``); 1 when it carries none (a client of the first rule)."""
    t = event["t"]
    if event["item_type"] not in ITEM_TYPES_FOR[t]:
        raise Reject("item_type")
    if t == EventType.FEED_IMPRESSION:
        idef = event.get("idef")
        if idef is None:
            event["impression_def"] = 1
        else:
            top = impression_def_max() if idef_max is None else idef_max
            if not 1 <= idef <= top:
                raise Reject("invalid_idef")
            event["impression_def"] = idef
    for name in REQUIRED[t]:
        if event.get(name) is None:
            raise Reject("missing_field")
    if t == EventType.VIDEO_REWATCH and event["play_index"] < 2:
        raise Reject("invalid_rewatch")
    if t == EventType.REEL_VIEW and event["watch_ms"] < REEL_VIEW_MIN_MS:
        raise Reject("short_view")


def check_skip(watch_ms: int, duration_ms: int | None) -> None:
    limit = SKIP_MAX_MS
    if duration_ms:
        limit = min(limit, int(SKIP_MAX_FRACTION * duration_ms))
    if watch_ms >= limit:
        raise Reject("invalid_skip")


def check_complete(watch_ms: int, duration_ms: int | None) -> None:
    if duration_ms and watch_ms < COMPLETE_MIN_FRACTION * duration_ms:
        raise Reject("early_complete")
