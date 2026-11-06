"""The exposure ledger v0 (06 sections 5.1-5.2, 07 WP 4b.3): what each viewer was
actually shown, in ``redis-hot``.

``feed:exp:{viewer}`` (named by ``hot.exposure_key``, stored through
``hot().make_key``) is a string used as an append log of 13-byte records::

    8 B  item id prefix (uuid.bytes[:8])
    4 B  epoch minute, big-endian; bit 31 is the compaction flag "two or more
         exposures" (a real minute never reaches it: 2^31 minutes is the year 6053)
    1 B  state (bits 0-1) | dwell-only consumption (bit 2) | visit_ord (bits 3-7)

The layout is a versioned wire format, not a tunable value: ``CODEC_VERSION`` is the
version of the records the key holds. Version 1 is the bare registered key (so
``hot.forget_account`` deletes it); a later codec gets a ``:v{n}`` suffix through
``ledger_key`` and must be registered in ``hot.raw_keys`` with it.

Writes come only from ``feed-signals`` ingest (``append_batch``): one Lua script per
batch, one round trip, no client-side read. The script stamps the viewer's current
``visit_ord`` (``HGET feed:sess visit_ord``, 0 when absent) on every record, appends,
refreshes the TTL and, only when the visit hash exists, raises its
``last_activity_at`` and counts displays (``dc``) and consumptions (``cc``). When an
append would take the log past ``2 x cap x 13`` bytes the script appends nothing and
ingest compacts instead (``GET`` + fold + a length-guarded ``SET``, rare), so the log
is never above 5.2 KB at cap 200 and is at most ``cap x 13`` = 2.6 KB compacted.

**``retrieved`` never produces a record**: nothing here runs at serve time. Every
write is fail-soft: a refusal (``noeviction`` OOM, timeout) is counted in
``intel_hot_write_failed_total{key="exp"}`` and ingest still returns 202 with its SQL
rows stored. The thresholds are the Home config's ``exposure`` block (decision 20).
"""

from __future__ import annotations

import logging
import struct
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from . import hot

logger = logging.getLogger("tara.intel.exposure")

CODEC_VERSION = 1
RECORD_BYTES = 13
PREFIX_BYTES = 8
VISIT_ORD_MOD = 32
METRIC_KEY = "exp"

# States (06 section 5.1; ``intel.models.ExposureState``). The highest one wins.
STATE_DISPLAYED = 0
STATE_SKIPPED = 1
STATE_VIEWED = 2
STATE_CONSUMED = 3
STATES = (STATE_DISPLAYED, STATE_SKIPPED, STATE_VIEWED, STATE_CONSUMED)

_STATE_MASK = 0b011
_DWELL_ONLY = 0b100
_MULTI = 0x8000_0000
_MINUTE_MASK = 0x7FFF_FFFF


def ledger_key(viewer_id) -> str:
    """The raw key name of the viewer's ledger (before ``make_key``)."""
    base = hot.exposure_key(viewer_id)
    return base if CODEC_VERSION == 1 else f"{base}:v{CODEC_VERSION}"


def item_prefix(item_id) -> bytes:
    return uuid.UUID(str(item_id)).bytes[:PREFIX_BYTES]


def epoch_minute(when: datetime | float | int) -> int:
    ts = when.timestamp() if isinstance(when, datetime) else float(when)
    return int(ts // 60) & _MINUTE_MASK


@dataclass(frozen=True)
class Record:
    """One record to append; ``visit_ord`` is stamped by the script at write time."""

    item_id: object
    state: int
    minute: int
    dwell_only: bool = False

    def encode(self, visit_ord: int = 0, *, multi: bool = False) -> bytes:
        return encode_record(
            item_prefix(self.item_id),
            self.minute,
            self.state,
            visit_ord,
            dwell_only=self.dwell_only,
            multi=multi,
        )


def encode_record(
    prefix: bytes,
    minute: int,
    state: int,
    visit_ord: int,
    *,
    dwell_only: bool = False,
    multi: bool = False,
) -> bytes:
    if len(prefix) != PREFIX_BYTES or state not in STATES:
        raise ValueError("bad exposure record")
    word = (int(minute) & _MINUTE_MASK) | (_MULTI if multi else 0)
    flags = state | (_DWELL_ONLY if dwell_only and state == STATE_CONSUMED else 0)
    return prefix + struct.pack(">I", word) + bytes([flags | ((visit_ord % VISIT_ORD_MOD) << 3)])


def decode(raw: bytes | None) -> list[tuple[bytes, int, int, int, bool, bool]]:
    """``(prefix, minute, state, visit_ord, dwell_only, multi)`` per whole record; a torn
    tail (shorter than a record) is ignored."""
    if not raw:
        return []
    out = []
    for at in range(0, len(raw) - RECORD_BYTES + 1, RECORD_BYTES):
        prefix = bytes(raw[at : at + PREFIX_BYTES])
        (word,) = struct.unpack(">I", raw[at + PREFIX_BYTES : at + 12])
        flags = raw[at + 12]
        out.append(
            (
                prefix,
                word & _MINUTE_MASK,
                flags & _STATE_MASK,
                flags >> 3,
                bool(flags & _DWELL_ONLY),
                bool(word & _MULTI),
            )
        )
    return out


@dataclass(frozen=True)
class Fold:
    """One item's folded ledger state (06 section 5.2)."""

    state: int  # the highest state reached
    minute: int  # the latest epoch minute
    exposures: int  # distinct visits with at least a display, capped at 2
    in_visit: bool  # displayed during the current visit
    dwell_only: bool = False  # consumed by dwell alone (no other consumption)
    visit_ord: int = 0  # the visit of the latest record


def fold(raw: bytes | None, current_visit_ord: int | None) -> dict[bytes, Fold]:
    """Fold the log per item prefix: the highest state wins, the latest minute is kept,
    ``exposures`` = distinct ``visit_ord`` values (every state is at least
    ``displayed``), capped at 2, so a reload or a second tab in the same visit is one
    exposure. A compacted record's flag counts as two. ``in_visit`` is whether any
    record of the item belongs to ``current_visit_ord`` (None: never)."""
    acc: dict[bytes, dict] = {}
    current = None if current_visit_ord is None else current_visit_ord % VISIT_ORD_MOD
    for prefix, minute, state, visit, dwell_only, multi in decode(raw):
        a = acc.get(prefix)
        if a is None:
            a = acc[prefix] = {
                "state": state,
                "minute": minute,
                "visits": set(),
                "multi": False,
                "in_visit": False,
                "dwell_only": None,
                "visit_ord": visit,
            }
        a["state"] = max(a["state"], state)
        if minute >= a["minute"]:
            a["minute"] = minute
            a["visit_ord"] = visit
        a["visits"].add(visit)
        a["multi"] = a["multi"] or multi
        a["in_visit"] = a["in_visit"] or (current is not None and visit == current)
        if state == STATE_CONSUMED:
            # Dwell-only until any other kind of consumption is seen.
            prev = a["dwell_only"]
            a["dwell_only"] = dwell_only if prev is None else prev and dwell_only
    out = {}
    for prefix, a in acc.items():
        exposures = 2 if a["multi"] else min(2, len(a["visits"]))
        out[prefix] = Fold(
            state=a["state"],
            minute=a["minute"],
            exposures=exposures,
            in_visit=a["in_visit"],
            dwell_only=bool(a["dwell_only"]) and a["state"] == STATE_CONSUMED,
            visit_ord=a["visit_ord"],
        )
    return out


def compact(raw: bytes, cap: int) -> bytes:
    """One record per item, the ``cap`` most recent items: ``cap x 13`` bytes at most.
    The record keeps the highest state, the latest minute and the latest visit (so
    ``in_visit`` stays exact for the visit that wrote it); "two or more exposures" is
    the flag in bit 31 of the minute word, never in the visit bits."""
    folded = fold(raw, None)
    # Most recent first: by minute, then by the position of the item's last record (a
    # batch shares one minute, so ties are common and the later append must win).
    last_at = {rec[0]: i for i, rec in enumerate(decode(raw))}
    newest = sorted(folded.items(), key=lambda kv: (kv[1].minute, last_at[kv[0]]), reverse=True)[
        : max(int(cap), 0)
    ]
    newest.reverse()  # oldest first, like an append log
    return b"".join(
        encode_record(
            prefix,
            f.minute,
            f.state,
            f.visit_ord,
            dwell_only=f.dwell_only,
            multi=f.exposures >= 2,
        )
        for prefix, f in newest
    )


# ---- Thresholds (the Home config's ``exposure`` block) --------------------------------


@dataclass(frozen=True)
class Thresholds:
    cap: int
    ttl_s: int
    skip_dwell_ms: int
    viewed_dwell_ms: int
    consumed_dwell_ms: int
    length_buckets: tuple[dict, ...]

    @property
    def max_bytes(self) -> int:
        return 2 * self.cap * RECORD_BYTES

    def consumed_ms(self, length_bucket: int | None) -> float:
        """The consumed-dwell threshold for an excerpt in ``length_bucket`` (the serve
        token's: 0 or None = unknown, then unscaled)."""
        if length_bucket and 1 <= length_bucket <= len(self.length_buckets):
            return self.consumed_dwell_ms * float(self.length_buckets[length_bucket - 1]["scale"])
        return float(self.consumed_dwell_ms)

    def dwell_state(self, dwell_ms: int, length_bucket: int | None) -> tuple[int, bool]:
        """``(state, dwell_only)`` of a ``feed_dwell``."""
        if dwell_ms >= self.consumed_ms(length_bucket):
            return STATE_CONSUMED, True
        if dwell_ms >= self.viewed_dwell_ms:
            return STATE_VIEWED, False
        if dwell_ms < self.skip_dwell_ms:
            return STATE_SKIPPED, False
        return STATE_DISPLAYED, False


def thresholds(cfg=None) -> Thresholds:
    """From ``cfg`` (a ``SurfaceConfig``) or the active Home config."""
    if cfg is None:
        from . import config

        cfg = config.for_surface("home")
    return Thresholds(
        cap=int(cfg.get("exposure.ledger.cap")),
        ttl_s=int(cfg.get("exposure.ledger.ttl_h")) * 3600,
        skip_dwell_ms=int(cfg.get("exposure.skip_dwell_ms")),
        viewed_dwell_ms=int(cfg.get("exposure.viewed_dwell_ms")),
        consumed_dwell_ms=int(cfg.get("exposure.consumed_dwell_ms")),
        length_buckets=tuple(cfg.get("exposure.length_buckets")),
    )


# ---- Writes ---------------------------------------------------------------------------

# KEYS: ledger, visit hash. ARGV: records (13 B each, visit bits zero), ttl_s, now (epoch
# s), displayed count, consumed count, max bytes. Returns {length or -1, visit_ord,
# length before}. -1: the append would pass max bytes, nothing was appended (compact).
# The shebang matters: a script without one that starts with a read may still write
# when redis-hot is past ``maxmemory`` (legacy EVAL rule); with it, Redis refuses the
# whole script in OOM, so ``noeviction`` really bounds memory and the refusal is counted.
_APPEND_LUA = """#!lua
local body = ARGV[1]
local vo = tonumber(redis.call('HGET', KEYS[2], 'visit_ord') or '0') or 0
vo = vo % 32
local parts = {}
for i = 1, #body - 12, 13 do
  local flags = string.byte(body, i + 12) % 8
  parts[#parts + 1] = string.sub(body, i, i + 11) .. string.char(flags + vo * 8)
end
local blob = table.concat(parts)
local before = redis.call('STRLEN', KEYS[1])
local len = -1
if before + #blob <= tonumber(ARGV[6]) then
  len = redis.call('APPEND', KEYS[1], blob)
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
if redis.call('EXISTS', KEYS[2]) == 1 then
  local now = tonumber(ARGV[3])
  local last = tonumber(redis.call('HGET', KEYS[2], 'last_activity_at') or '0') or 0
  if now > last then redis.call('HSET', KEYS[2], 'last_activity_at', ARGV[3]) end
  if tonumber(ARGV[4]) > 0 then redis.call('HINCRBY', KEYS[2], 'dc', ARGV[4]) end
  if tonumber(ARGV[5]) > 0 then redis.call('HINCRBY', KEYS[2], 'cc', ARGV[5]) end
end
return {len, vo, before}
"""

# KEYS: ledger. ARGV: expected length, new value, ttl_s. Sets only when the log did not
# change since it was read (a concurrent append is never lost).
_SWAP_LUA = """#!lua
if redis.call('STRLEN', KEYS[1]) ~= tonumber(ARGV[1]) then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3]))
return 1
"""

_scripts: dict = {}


def _script(client, name: str, source: str):
    """The registered script, always run on ``client`` (a cached ``Script`` must never
    fall back to the client it was first registered with)."""
    script = _scripts.get(name)
    if script is None:
        script = _scripts[name] = client.register_script(source)

    def run(keys, args):
        return script(keys=keys, args=args, client=client)

    return run


def _failed(exc: Exception | None = None) -> bool:
    from . import metrics

    metrics.hot_write_failed(METRIC_KEY)
    logger.warning("redis-hot refused an exposure write", exc_info=exc is not None)
    return False


def append_batch(
    viewer_id,
    records: Iterable[Record],
    th: Thresholds,
    *,
    now: datetime | float,
    displayed: int | None = None,
    client=None,
) -> bool:
    """Append ``records`` for ``viewer_id`` (ingest). True when they are in the ledger.
    ``displayed``: the visit's display counter increment (``dc``; default: one per
    record). Fail-soft: never raises; a refusal is counted and returns False."""
    records = list(records)
    if not records:
        return True
    client = client if client is not None else hot.raw_client()
    if client is None:
        return False
    backend = hot.hot()
    exp_key = backend.make_key(ledger_key(viewer_id))
    sess_key = backend.make_key(hot.visit_key(viewer_id))
    blob = b"".join(r.encode(0) for r in records)
    displayed = len(records) if displayed is None else int(displayed)
    consumed = sum(1 for r in records if r.state == STATE_CONSUMED)
    now_s = int(now.timestamp() if isinstance(now, datetime) else now)
    try:
        length, visit_ord, before = _script(client, "append", _APPEND_LUA)(
            [exp_key, sess_key], [blob, th.ttl_s, now_s, displayed, consumed, th.max_bytes]
        )
    except Exception as exc:  # noqa: BLE001 - a full or down redis-hot only costs this state
        return _failed(exc)
    if int(length) >= 0:
        return True
    return _compact(client, exp_key, records, int(visit_ord), int(before), th)


def _compact(client, exp_key, records, visit_ord: int, before: int, th: Thresholds) -> bool:
    """The log is full: fold it with the new records and rewrite it (rare)."""
    stamped = b"".join(r.encode(visit_ord) for r in records)
    for _ in range(3):
        try:
            raw = client.get(exp_key) or b""
            value = compact(bytes(raw) + stamped, th.cap)
            if _script(client, "swap", _SWAP_LUA)([exp_key], [len(raw), value, th.ttl_s]):
                return True
        except Exception as exc:  # noqa: BLE001
            return _failed(exc)
    return _failed()


def append_records(viewer_id, records, cfg=None) -> bool:
    """Public helper (Track A's repetition harness): append ``records`` (``Record``
    values, or ``(item_id, state, minute[, dwell_only])`` tuples) at their own minutes,
    through the same script ingest uses. ``cfg``: a ``SurfaceConfig`` (default: active
    Home). Fail-soft like ingest."""
    th = thresholds(cfg)
    built = [r if isinstance(r, Record) else Record(*r) for r in records]
    now = max((r.minute for r in built), default=0) * 60
    return append_batch(viewer_id, built, th, now=now)


def load(viewer_id, current_visit_ord: int | None, *, client=None) -> dict[bytes, Fold]:
    """The viewer's folded ledger (one ``GET``); empty when unreadable."""
    client = client if client is not None else hot.raw_client()
    if client is None:
        return {}
    try:
        raw = client.get(hot.hot().make_key(ledger_key(viewer_id)))
    except Exception:  # noqa: BLE001 - an unreadable ledger ranks as an empty one
        logger.warning("redis-hot unreadable (exposure ledger)", exc_info=True)
        return {}
    return fold(raw, current_visit_ord)
