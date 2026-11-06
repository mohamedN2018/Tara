"""The visit (06 sections 4.1 to 4.3, 07 WP 4b.4): refresh, ongoing, new, returning, lapsed.

A Home first page is classified **from server timestamps only**: the client's ``sid``
(its telemetry session id) and ``entry`` (how it reached the page) are hints. A wrong
or forged hint can at most change which of the viewer's own items are rotated, never
eligibility, and it cannot turn a refresh into a new visit (that needs the server's
idle gap). Thresholds are the Home config's ``session`` block (decision 20):

==========  ===================================================================
refresh     a first page on the same surface less than ``refresh_max_s`` after the
            previous one, or ``entry`` reload/pull while the visit is ongoing
ongoing     last activity less than ``ongoing_idle_s`` ago
new         idle, and the current visit started less than ``returning_after_h`` ago
returning   idle, and the current visit started ``returning_after_h`` or more ago
lapsed      returning after ``lapsed_after_d`` days or more (a longer new-since window)
==========  ===================================================================

State lives in ``feed:sess:{viewer}`` (a raw hash, TTL 8 days, ``hot.visit_key``).
Field names are a contract with ``feed-signals`` ingest (R3 track B), which only
raises ``last_activity_at`` and counts ``dc`` / ``cc`` when the hash exists:

``visit_id`` (uuid hex), ``visit_ord`` (0-31), ``kind``, ``visit_started_at``,
``prev_visit_started_at``, ``last_activity_at``, ``sid``, ``fp:{surface}`` (the last
first page there), counters ``fp`` (first pages), ``rf`` (refreshes), ``dc``
(displayed), ``cc`` (consumed). Times are integer epoch seconds. Track A also keeps
``nc`` / ``na``: the visit's new-since count and anchor of its last ranked first page,
so a reused frozen list (a reload) shows the same divider without a re-count.

``intel_feed_session`` (``FeedSession``) keeps one row per visit: an ``INSERT`` at the
visit start and one ``UPDATE`` closing the previous visit with the counters, so a
new-visit first page costs **2 SQL writes** and every other request **0**. On a Redis
miss the latest row stands in for the hash. ``last_visit_at`` (the ``since`` of "new
since your last visit") moves only on new, returning and lapsed visits.

``personalization_off`` (decision 24): nothing is written, not even the timestamps,
and ``meta.visit`` is null. Every Redis write is fail-soft and counted in
``intel_hot_write_failed_total{key="sess"}``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from django.db import connection

from . import hot, metrics

logger = logging.getLogger("tara.intel.session_ctx")

METRIC_KEY = "sess"
TTL_S = 8 * 24 * 3600  # 06 section 4.3: a returning user within a week needs no DB read
VISIT_ORD_MOD = 32

REFRESH, ONGOING, NEW, RETURNING, LAPSED = "refresh", "ongoing", "new", "returning", "lapsed"
NEW_VISIT_KINDS = frozenset({NEW, RETURNING, LAPSED})
# The hints (06 section 4.2) plus the R2 names the web already sends: ``open`` is in-app
# navigation, ``refresh`` the refresh control (a pull).
ENTRIES = ("nav", "load", "reload", "return", "pull", "open", "refresh")
_ALIASES = {"open": "nav", "refresh": "pull"}
DELIBERATE = frozenset({"reload", "pull"})
COUNTERS = ("fp", "rf", "dc", "cc")


def normalize_entry(entry: str | None) -> str:
    """The hint as one of ``nav, load, reload, return, pull`` (``load`` when absent)."""
    if not entry:
        return "load"
    return _ALIASES.get(entry, entry)


def _epoch(when: datetime) -> int:
    return int(when.timestamp())


def _when(epoch: int | None) -> datetime | None:
    return None if epoch is None else datetime.fromtimestamp(int(epoch), tz=UTC)


def _int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value.decode() if isinstance(value, bytes) else value)
    except (TypeError, ValueError):
        return None


def decode_hash(raw) -> dict[str, str]:
    """``HGETALL`` bytes to ``{field: value}`` strings (empty for a missing key)."""
    if not raw:
        return {}
    out = {}
    for k, v in raw.items():
        out[k.decode() if isinstance(k, bytes) else str(k)] = (
            v.decode() if isinstance(v, bytes) else str(v)
        )
    return out


@dataclass
class Visit:
    """One first page's view of the visit. ``since`` is ``last_visit_at``: the start of
    the previous visit (None for a first visit ever), clamped to ``new_since.max_age_h``."""

    kind: str
    visit_id: str
    visit_ord: int
    started_at: int
    since: datetime | None
    entry: str
    surface: str
    now: int
    sid: str | None = None
    # What the closing UPDATE / the hash write need.
    previous_id: str | None = None
    previous_started_at: int | None = None
    previous_last_activity: int | None = None
    previous_counters: dict = field(default_factory=dict)
    last_activity_at: int | None = None
    from_sql: bool = False
    hash_found: bool = False
    stored_new_count: int = 0
    stored_anchor: int | None = None

    @property
    def is_new(self) -> bool:
        return self.kind in NEW_VISIT_KINDS

    @property
    def is_lapsed(self) -> bool:
        return self.kind == LAPSED


def session_cfg(cfg) -> dict:
    return cfg.section("session")


def _latest_row(viewer_id) -> dict | None:
    """The latest ``intel_feed_session`` row (one read, only on a Redis miss)."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT id, started_at, last_activity_at FROM intel_feed_session"
            " WHERE account_id = %s ORDER BY started_at DESC LIMIT 1",
            [str(viewer_id)],
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "visit_id": uuid.UUID(str(row[0])).hex,
        "visit_started_at": str(_epoch(row[1])),
        "last_activity_at": str(_epoch(row[2])),
    }


def classify(
    viewer_id,
    surface: str,
    now: datetime,
    cfg,
    *,
    entry: str | None,
    sid: str | None,
    state: dict | None,
) -> Visit:
    """The kind of this first page. ``state`` is the decoded ``feed:sess`` hash (from
    the caller's pipelined read; ``{}`` when absent, None when redis-hot was
    unreadable). Reads SQL only when the hash is missing. Writes nothing."""
    s = session_cfg(cfg)
    hint = normalize_entry(entry)
    now_s = _epoch(now)
    found = bool(state)
    from_sql = False
    h = dict(state or {})
    if not found:
        row = _latest_row(viewer_id)
        if row is not None:
            h, from_sql = row, True
    last = _int(h.get("last_activity_at"))
    started = _int(h.get("visit_started_at"))
    first_here = _int(h.get(f"fp:{surface}"))
    ord_now = _int(h.get("visit_ord")) or 0
    if last is not None and now_s - last < s["ongoing_idle_s"]:
        recent_fp = first_here is not None and 0 <= now_s - first_here < s["refresh_max_s"]
        kind = REFRESH if recent_fp or hint in DELIBERATE else ONGOING
    elif started is None:
        kind = NEW  # the first visit ever
    elif now_s - started < s["returning_after_h"] * 3600:
        kind = NEW
    elif now_s - started >= s["lapsed_after_d"] * 86400:
        kind = LAPSED
    else:
        kind = RETURNING
    if kind in NEW_VISIT_KINDS:
        visit = Visit(
            kind=kind,
            visit_id=uuid.uuid4().hex,
            visit_ord=((ord_now + 1) % VISIT_ORD_MOD) if (found or from_sql) else 0,
            started_at=now_s,
            since=_when(started),
            entry=hint,
            surface=surface,
            now=now_s,
            sid=sid,
            previous_id=h.get("visit_id"),
            previous_started_at=started,
            previous_last_activity=last,
            previous_counters={k: _int(h.get(k)) or 0 for k in COUNTERS} if found else {},
            last_activity_at=now_s,
            from_sql=from_sql,
            hash_found=found,
        )
    else:
        visit = Visit(
            kind=kind,
            visit_id=h.get("visit_id") or uuid.uuid4().hex,
            visit_ord=ord_now % VISIT_ORD_MOD,
            started_at=started if started is not None else now_s,
            since=_when(_int(h.get("prev_visit_started_at"))),
            entry=hint,
            surface=surface,
            now=now_s,
            sid=sid,
            last_activity_at=max(now_s, last or now_s),
            from_sql=from_sql,
            hash_found=found,
            stored_new_count=_int(h.get("nc")) or 0,
            stored_anchor=_int(h.get("na")),
        )
    floor = now - timedelta(hours=s["new_since"]["max_age_h"])
    if visit.since is not None and visit.since < floor:
        visit.since = floor
    return visit


def _write_hash(viewer_id, visit: Visit, client, new_count: int, anchor: int | None) -> bool:
    """The hash update of one first page, one round trip, fail-soft."""
    name = hot.hot().make_key(hot.visit_key(viewer_id))
    fields = {
        "last_activity_at": str(visit.last_activity_at or visit.now),
        f"fp:{visit.surface}": str(visit.now),
        "nc": str(int(new_count)),
        "na": "" if anchor is None else str(int(anchor)),
    }
    if visit.sid:
        fields["sid"] = visit.sid
    restart = visit.is_new or not visit.hash_found
    if restart:
        fields.update(
            {
                "visit_id": visit.visit_id,
                "visit_ord": str(visit.visit_ord),
                "kind": visit.kind,
                "visit_started_at": str(visit.started_at),
            }
        )
        if visit.is_new and visit.previous_started_at is not None:
            fields["prev_visit_started_at"] = str(visit.previous_started_at)
        elif visit.since is not None:
            fields["prev_visit_started_at"] = str(_epoch(visit.since))
    try:
        # MULTI/EXEC: still one round trip, and ingest never sees the hash half reset.
        pipe = client.pipeline(transaction=True)
        if visit.is_new:
            pipe.delete(name)  # the previous visit's counters were flushed to SQL
        pipe.hset(name, mapping=fields)
        if visit.is_new:
            pipe.hset(name, mapping={"fp": "1", "rf": "0", "dc": "0", "cc": "0"})
        else:
            pipe.hincrby(name, "fp", 1)
            if visit.kind == REFRESH:
                pipe.hincrby(name, "rf", 1)
        pipe.expire(name, TTL_S)
        pipe.execute()
        return True
    except Exception:  # noqa: BLE001 - a full or down redis-hot only costs the visit state
        metrics.hot_write_failed(METRIC_KEY)
        logger.warning("redis-hot refused a visit write", exc_info=True)
        return False


_INSERT_SQL = """
INSERT INTO intel_feed_session (id, account_id, client_sid, kind, entry_surface, started_at,
    last_activity_at, ended_at, first_pages, refreshes, displayed, consumed, new_since_count,
    intent, head_overlap, data_origin)
VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, 1, 0, 0, 0, %s, NULL, %s, %s)
"""
_CLOSE_SQL = """
UPDATE intel_feed_session SET ended_at = %s, last_activity_at = %s,
    first_pages = %s, refreshes = %s, displayed = %s, consumed = %s
WHERE id = %s AND account_id = %s
"""
_SMALLINT = 32_767


def _uuid_or_none(value) -> str | None:
    try:
        return str(uuid.UUID(str(value))) if value else None
    except (TypeError, ValueError):
        return None


def finish(
    viewer_id,
    visit: Visit,
    *,
    new_count: int = 0,
    anchor_index: int | None = None,
    head_overlap: float | None = None,
    client=None,
) -> int:
    """Store this first page: the hash update (Redis, fail-soft) and, on a new visit,
    the new row plus the close of the previous one. Returns the SQL writes made."""
    client = client if client is not None else hot.raw_client()
    if client is not None:
        _write_hash(viewer_id, visit, client, new_count, anchor_index)
    if not visit.is_new:
        return 0
    return _write_rows(viewer_id, visit, new_count, head_overlap)


def _write_rows(viewer_id, visit: Visit, new_count: int, head_overlap: float | None) -> int:
    """The new visit's row and the close of the previous one (2 statements)."""
    from . import origin

    writes = 0
    account = str(viewer_id)
    with connection.cursor() as cur:
        cur.execute(
            _INSERT_SQL,
            [
                str(uuid.UUID(visit.visit_id)),
                account,
                _uuid_or_none(visit.sid),
                visit.kind,
                visit.surface[:12],
                _when(visit.started_at),
                _when(visit.now),
                min(max(int(new_count), 0), _SMALLINT),
                head_overlap,
                origin.resolve(account).origin,
            ],
        )
        writes += 1
        previous = _uuid_or_none(visit.previous_id)
        if previous is not None:
            ended = _when(visit.previous_last_activity or visit.previous_started_at)
            c = visit.previous_counters
            cur.execute(
                _CLOSE_SQL,
                [
                    ended,
                    ended,
                    min(c.get("fp", 0), _SMALLINT),
                    min(c.get("rf", 0), _SMALLINT),
                    c.get("dc", 0),
                    c.get("cc", 0),
                    previous,
                    account,
                ],
            )
            writes += 1
    return writes


_TOUCH_LUA = """
if redis.call('EXISTS', KEYS[1]) == 1 then
  local last = tonumber(redis.call('HGET', KEYS[1], 'last_activity_at') or '0') or 0
  if tonumber(ARGV[1]) > last then redis.call('HSET', KEYS[1], 'last_activity_at', ARGV[1]) end
  return 1
end
return 0
"""


def touch(viewer_id, now: datetime) -> None:
    """A later page is activity too (06 section 4.2): raise ``last_activity_at`` when the
    hash exists. Never creates the hash (so nothing is written for a viewer the
    first page did not record, ``personalization_off`` included). Fail-soft."""
    client = hot.raw_client()
    if client is None:
        return
    try:
        client.eval(_TOUCH_LUA, 1, hot.hot().make_key(hot.visit_key(viewer_id)), _epoch(now))
    except Exception:  # noqa: BLE001
        metrics.hot_write_failed(METRIC_KEY)
        logger.warning("redis-hot refused a visit touch", exc_info=True)


def meta(visit: Visit | None, cfg, *, new_count: int, anchor_index: int | None) -> dict | None:
    """``meta.visit`` of a first page (06 section 6.2); None under personalization_off."""
    if visit is None:
        return None
    return {
        "kind": visit.kind,
        "since": visit.since.isoformat() if visit.since is not None else None,
        "new_count": int(new_count),
        "anchor_index": anchor_index,
        "min_to_show": int(cfg.get("session.new_since.min_to_show")),
    }


def purge(cfg, now: datetime | None = None) -> int:
    """Delete visit rows older than ``session.feed_session_retention_d`` (nightly)."""
    from django.utils import timezone

    days = int(cfg.get("session.feed_session_retention_d"))
    cutoff = (now or timezone.now()) - timedelta(days=days)
    with connection.cursor() as cur:
        cur.execute("DELETE FROM intel_feed_session WHERE started_at < %s", [cutoff])
        return cur.rowcount
