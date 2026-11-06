"""SignalCollectionService: one client batch into ``intel_signal_event`` (WP 2.3).

Order of work for one batch (all in the request's transaction):

1. Origin: the account's ``intel_synthetic_account`` label (in-process registry) gives
   ``real``, ``synthetic`` or ``test``; a registered account in an environment that
   does not accept synthetic rows stores nothing.
2. Batch claim and the ``personalization_off`` gate in one statement (07 WP 4b.16):
   the ``intel_signal_batch`` insert runs only when the account has not turned
   personalization off (``NOT EXISTS`` on ``intel_user_preference``), and
   ``ON CONFLICT DO NOTHING`` makes a retried batch change nothing. Under
   ``personalization_off`` nothing is written anywhere: no row, no ledger record,
   no visit counter (owner decision 24).
3. Per event: shape, ``ts`` clamp (+-24 h), serve-token attribution, ``watch_ms``
   clamp, the video state rules (complete needs a start, rewatch needs a complete)
   and the wall-clock check (a session cannot claim more watch time per 60 s than
   60 s plus 10 %). A failing event is dropped and counted, never the batch.
4. One ``COPY`` of the accepted rows.
5. The exposure ledger (07 WP 4b.3, ``intel.exposure``): the accepted rows' states
   in one Lua call (one ``redis-hot`` round trip), fail-soft.

Queries: the conditional batch insert, the ``COPY``, and only when the batch carries
video events, one read of the session's earlier video rows (the last 24 h). Redis:
one script call (a compaction, rare, adds a ``GET`` and a guarded ``SET``).

``feed_dwell`` (WP 4b.2) is stored with its dwell in ``watch_ms`` (the column holds
"milliseconds of attention" for this one type; ``WATCH_EVENTS`` never includes it)
and, in ``duration_ms``, the consumed-dwell threshold its excerpt length needed.
A second ``feed_dwell`` for the same (session, item) in one batch is dropped
(``duplicate_dwell``); across batches the client sends one, and the aggregator keeps
one per (session, item) (``intel.signals.aggregate``).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from django.db import connection
from django.utils import timezone

from .. import exposure, metrics, origin
from ..models import EventType, ItemType, SignalFlag, SignalSource
from ..ranking import serve_tokens
from . import store, validate
from .serializers import SignalEventSerializer, rejection_reason
from .validate import Reject


@dataclass
class IngestResult:
    accepted: int = 0
    duplicate: bool = False
    rejected: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "duplicate": self.duplicate,
            "rejected": dict(sorted(self.rejected.items())),
        }


_CLAIM_SQL = (
    "WITH off AS (SELECT EXISTS (SELECT 1 FROM intel_user_preference "
    "WHERE account_id = %s AND personalization_off) AS v), "
    "ins AS (INSERT INTO intel_signal_batch (account_id, batch_id, received_at) "
    "SELECT %s, %s, %s FROM off WHERE NOT off.v ON CONFLICT DO NOTHING RETURNING 1) "
    "SELECT (SELECT v FROM off), (SELECT count(*) FROM ins)"
)


def _claim_batch(account_id, batch_id, now: datetime) -> tuple[bool, bool]:
    """``(claimed, personalization_off)`` in one statement (no extra query)."""
    with connection.cursor() as cur:
        cur.execute(_CLAIM_SQL, [account_id, account_id, batch_id, now])
        off, inserted = cur.fetchone()
    return inserted == 1, bool(off)


@dataclass
class _SessionState:
    """The session's video history: plays' highest watch, starts and completions."""

    max_watch: dict = field(default_factory=dict)  # (item_id, play_index) -> ms
    current_play: dict = field(default_factory=dict)  # item_id -> latest started play_index
    started: set = field(default_factory=set)  # item_id
    completed: set = field(default_factory=set)  # item_id
    budget_ms: float = 0.0  # watch time still claimable in the current 60 s window


def _load_session(account_id, session_id, now: datetime) -> _SessionState:
    state = _SessionState()
    recent_claims = 0
    window_start = now - validate.WALL_CLOCK_WINDOW
    with connection.cursor() as cur:
        cur.execute(
            "SELECT event_type, item_id, play_index, watch_ms, received_at "
            "FROM intel_signal_event WHERE account_id = %s AND session_id = %s "
            "AND source = 'client' AND received_at >= %s AND event_type = ANY(%s) "
            "ORDER BY received_at, id",
            [
                account_id,
                session_id,
                now - validate.TS_WINDOW,
                [str(t) for t in validate.VIDEO_STATE_EVENTS],
            ],
        )
        for event_type, item_id, play_index, watch_ms, received_at in cur.fetchall():
            key = str(item_id)
            if event_type == EventType.VIDEO_START:
                state.started.add(key)
                state.current_play[key] = play_index or 1
            elif event_type == EventType.VIDEO_COMPLETE:
                state.completed.add(key)
            if event_type in validate.WATCH_EVENTS and watch_ms is not None:
                play = (key, play_index or state.current_play.get(key, 1))
                claim = max(0, watch_ms - state.max_watch.get(play, 0))
                state.max_watch[play] = max(state.max_watch.get(play, 0), watch_ms)
                if received_at >= window_start:
                    recent_claims += claim
    window_ms = validate.WALL_CLOCK_WINDOW.total_seconds() * 1000
    state.budget_ms = window_ms * validate.WALL_CLOCK_TOLERANCE - recent_claims
    return state


def _attribution(event: dict, account_id) -> dict:
    """Server-stamped attribution from a valid serve token, else the client's hint."""
    claims = None
    if event.get("st"):
        claims = serve_tokens.verify(event["st"], account_id, event["item_type"], event["item_id"])
    if claims is None:
        hint = (event.get("surface") or "").strip()
        return {
            "attributed": False,
            "surface": hint if hint in validate.UNATTRIBUTED_SURFACE_HINTS else None,
            "position": event.get("pos") if event["t"] == EventType.FEED_IMPRESSION else None,
            # Until intel_content_ref (WP 3.1) can tell that an item is public, live
            # and not in a group, every unattributed row is flagged: aggregation then
            # counts it for the viewer's own profile only (fail closed).
            "flags": SignalFlag.INELIGIBLE_ITEM,
        }
    return {
        "attributed": True,
        "surface": claims.surface,
        "position": claims.position,
        "cfg_version": claims.cfg_version,
        "variant": claims.variant,
        "rank_source": claims.source,
        "pred": claims.scores
        if event["t"] == EventType.FEED_IMPRESSION and claims.scores
        else None,
        "flags": 0,
        "claims": claims,
    }


def _video_rules(event: dict, state: _SessionState, row: store.SignalRow) -> None:
    t, key = event["t"], str(event["item_id"])
    duration = row.duration_ms
    if t == EventType.VIDEO_START:
        state.current_play[key] = row.play_index or 1
    elif t in validate.WATCH_EVENTS and row.play_index is None:
        # The web tracker names the play on video_start only; later watch events of
        # that play carry its cumulative watch time (frontend/web/src/lib/videoSignals.ts).
        row.play_index = state.current_play.get(key, 1)
    if t in validate.WATCH_EVENTS:
        ceiling = validate.watch_ceiling_ms(duration)
        if row.watch_ms > ceiling:
            row.watch_ms = ceiling
            row.flags |= SignalFlag.WATCH_CLAMPED
    if t == EventType.VIDEO_SKIP:
        validate.check_skip(row.watch_ms, duration)
    if t == EventType.VIDEO_COMPLETE:
        if key not in state.started:
            raise Reject("complete_without_start")
        validate.check_complete(row.watch_ms, duration)
    if t == EventType.VIDEO_REWATCH and key not in state.completed:
        raise Reject("rewatch_without_complete")
    if t in validate.WATCH_EVENTS:
        play = (key, row.play_index)
        claim = max(0, row.watch_ms - state.max_watch.get(play, 0))
        if claim > state.budget_ms:
            raise Reject("watch_overclaim")
        state.budget_ms -= claim
        state.max_watch[play] = max(state.max_watch.get(play, 0), row.watch_ms)
    if t == EventType.VIDEO_START:
        state.started.add(key)
    elif t == EventType.VIDEO_COMPLETE:
        state.completed.add(key)


# ---- The exposure ledger (07 WP 4b.3) ---------------------------------------------------

_LEDGER_KINDS = frozenset({ItemType.POST, ItemType.REEL, ItemType.VIDEO})
_NO_LEDGER = object()  # the thresholds could not be read: rows are stored, no ledger
_FIXED_STATES = {
    EventType.FEED_IMPRESSION: exposure.STATE_DISPLAYED,
    # Autoplay is muted (R2 video policy): a start or progress is a display only.
    EventType.VIDEO_START: exposure.STATE_DISPLAYED,
    EventType.VIDEO_PROGRESS: exposure.STATE_DISPLAYED,
    EventType.VIDEO_SKIP: exposure.STATE_SKIPPED,
    EventType.POST_OPEN: exposure.STATE_VIEWED,
    EventType.REEL_VIEW: exposure.STATE_VIEWED,
    EventType.VIDEO_COMPLETE: exposure.STATE_CONSUMED,
    EventType.VIDEO_REWATCH: exposure.STATE_CONSUMED,
}


def _thresholds():
    try:
        return exposure.thresholds()
    except Exception:  # noqa: BLE001 - the SQL rows still commit (fail-soft)
        metrics.hot_write_failed(exposure.METRIC_KEY)
        return _NO_LEDGER


def _ledger_state(event: dict, row, claims, th) -> tuple[int, bool] | None:
    """The exposure state an accepted event records, or None (profile visits; an item
    that is not a post, reel or video). ``feed_dwell``: by its dwell, the consumed
    threshold scaled by the excerpt length bucket of its serve token v2."""
    if th is _NO_LEDGER or event["item_type"] not in _LEDGER_KINDS:
        return None
    t = event["t"]
    if t == EventType.FEED_DWELL:
        bucket = claims.length_bucket if claims is not None else None
        # The row keeps the reading time this card needed (the scaled consumed
        # threshold) in ``duration_ms``: the aggregator classifies its dwell the same
        # way without the token (``intel.signals.aggregate``).
        row.duration_ms = round(th.consumed_ms(bucket))
        return th.dwell_state(row.watch_ms, bucket)
    if t in _FIXED_STATES:
        return _FIXED_STATES[t], False
    return None


def _append_ledger(account_id, marks: list, th, now: datetime) -> None:
    minute = exposure.epoch_minute(now)
    records = [
        exposure.Record(row.item_id, st, minute, dwell_only=dwell_only)
        for row, st, dwell_only in marks
    ]
    displayed = sum(1 for row, _, _ in marks if row.event_type == EventType.FEED_IMPRESSION)
    exposure.append_batch(account_id, records, th, now=now, displayed=displayed)


def ingest(account_id, batch: dict, *, now: datetime | None = None) -> IngestResult:
    """Validate and store one batch for ``account_id`` (the authenticated account)."""
    now = now or timezone.now()
    result = IngestResult()
    resolution = origin.resolve(account_id)
    if resolution.refused:
        result.rejected["synthetic_not_accepted"] = len(batch["events"])
        metrics.rejected("synthetic_not_accepted", len(batch["events"]))
        return result
    claimed, off = _claim_batch(account_id, batch["batch_id"], now)
    if off:
        # Decision 24: personalization off stores nothing behavioural, anywhere.
        result.rejected["personalization_off"] = len(batch["events"])
        metrics.rejected("personalization_off", len(batch["events"]))
        return result
    if not claimed:
        result.duplicate = True
        return result

    events = []
    for raw in batch["events"]:
        ser = SignalEventSerializer(data=raw)
        if not ser.is_valid():
            result.rejected[rejection_reason(ser.errors)] += 1
            continue
        events.append(ser.validated_data)

    state = None
    if any(e["t"] in validate.VIDEO_STATE_EVENTS for e in events):
        state = _load_session(account_id, batch["session_id"], now)

    rows = []
    ledger = []  # (row, state, dwell_only)
    th = None
    dwell_seen: set = set()
    idef_max = (
        validate.impression_def_max()
        if any(e["t"] == EventType.FEED_IMPRESSION for e in events)
        else None
    )
    for event in events:
        try:
            validate.check_shape(event, idef_max=idef_max)
            occurred, flags = event["ts"], 0
            if abs(occurred - now) > validate.TS_WINDOW:
                occurred, flags = now, SignalFlag.TS_CLAMPED
            attribution = _attribution(event, account_id)
            row = store.SignalRow(
                account_id=account_id,
                event_type=event["t"],
                item_type=event["item_type"],
                item_id=event["item_id"],
                source=SignalSource.CLIENT,
                data_origin=resolution.origin,
                occurred_at=occurred,
                received_at=now,
                client_event_id=event["id"],
                batch_id=batch["batch_id"],
                session_id=batch["session_id"],
                watch_ms=event.get("watch_ms"),
                pos_ms=event.get("pos_ms"),
                play_index=event.get("play_index"),
                impression_def=event.get("impression_def"),
                **{k: v for k, v in attribution.items() if k not in ("flags", "claims")},
            )
            row.flags = flags | attribution["flags"]
            if event["t"] in validate.VIDEO_STATE_EVENTS:
                _video_rules(event, state, row)
            claims = attribution.get("claims")
            if event["t"] == EventType.FEED_DWELL:
                key = str(event["item_id"])
                if key in dwell_seen:
                    raise Reject("duplicate_dwell")
                validate.check_dwell(
                    event["dwell_ms"], claims.issued_at if claims else None, now.timestamp()
                )
                dwell_seen.add(key)
                row.watch_ms = event["dwell_ms"]
            if th is None and event["item_type"] in _LEDGER_KINDS:
                th = _thresholds()
            mark = _ledger_state(event, row, claims, th) if th is not None else None
        except Reject as exc:
            result.rejected[exc.reason] += 1
            continue
        rows.append(row)
        if mark is not None:
            ledger.append((row, *mark))

    result.accepted = store.copy_rows(rows)
    if ledger and th is not None and th is not _NO_LEDGER:
        _append_ledger(account_id, ledger, th, now)
    metrics.accepted(resolution.origin, result.accepted)
    for reason, n in result.rejected.items():
        metrics.rejected(reason, n)
    return result
