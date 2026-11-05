"""SignalCollectionService: one client batch into ``intel_signal_event`` (WP 2.3).

Order of work for one batch (all in the request's transaction):

1. Origin: the account's ``intel_synthetic_account`` label (in-process registry) gives
   ``real``, ``synthetic`` or ``test``; a registered account in an environment that
   does not accept synthetic rows stores nothing.
2. Batch dedupe: ``INSERT ... ON CONFLICT DO NOTHING`` into ``intel_signal_batch``;
   a retried batch changes nothing.
3. Per event: shape, ``ts`` clamp (+-24 h), serve-token attribution, ``watch_ms``
   clamp, the video state rules (complete needs a start, rewatch needs a complete)
   and the wall-clock check (a session cannot claim more watch time per 60 s than
   60 s plus 10 %). A failing event is dropped and counted, never the batch.
4. One ``COPY`` of the accepted rows.

Queries: the batch insert, the ``COPY``, and only when the batch carries video
events, one read of the session's earlier video rows (the last 24 h).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from django.db import connection
from django.utils import timezone

from .. import metrics, origin
from ..models import EventType, SignalFlag, SignalSource
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


def _claim_batch(account_id, batch_id, now: datetime) -> bool:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO intel_signal_batch (account_id, batch_id, received_at) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            [account_id, batch_id, now],
        )
        return cur.rowcount == 1


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


def ingest(account_id, batch: dict, *, now: datetime | None = None) -> IngestResult:
    """Validate and store one batch for ``account_id`` (the authenticated account)."""
    now = now or timezone.now()
    result = IngestResult()
    resolution = origin.resolve(account_id)
    if resolution.refused:
        result.rejected["synthetic_not_accepted"] = len(batch["events"])
        metrics.rejected("synthetic_not_accepted", len(batch["events"]))
        return result
    if not _claim_batch(account_id, batch["batch_id"], now):
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
    for event in events:
        try:
            validate.check_shape(event)
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
                **{k: v for k, v in attribution.items() if k != "flags"},
            )
            row.flags = flags | attribution["flags"]
            if event["t"] in validate.VIDEO_STATE_EVENTS:
                _video_rules(event, state, row)
        except Reject as exc:
            result.rejected[exc.reason] += 1
            continue
        rows.append(row)

    result.accepted = store.copy_rows(rows)
    metrics.accepted(resolution.origin, result.accepted)
    for reason, n in result.rejected.items():
        metrics.rejected(reason, n)
    return result
