"""R3 WP 4b.3: the exposure ledger codec (13-byte records), ``fold`` and compaction.

Pure functions: no database, no Redis."""

import struct
import uuid

import pytest

from intel import exposure as x


def _rec(item, minute, state, visit, **kw):
    return x.encode_record(x.item_prefix(item), minute, state, visit, **kw)


def test_record_is_thirteen_bytes_and_round_trips():
    item = uuid.uuid4()
    raw = _rec(item, 29_000_000, x.STATE_VIEWED, 21)
    assert len(raw) == x.RECORD_BYTES == 13
    assert raw[:8] == item.bytes[:8]
    (prefix, minute, state, visit, dwell_only, multi) = x.decode(raw)[0]
    assert (prefix, minute, state, visit, dwell_only, multi) == (
        item.bytes[:8],
        29_000_000,
        x.STATE_VIEWED,
        21,
        False,
        False,
    )
    # state in bits 0-1 (bit 2: dwell-only consumption), visit_ord in bits 3-7
    assert raw[12] == x.STATE_VIEWED | (21 << 3)


def test_visit_ord_wraps_mod_32_and_bad_records_are_refused():
    item = uuid.uuid4()
    assert x.decode(_rec(item, 1, x.STATE_DISPLAYED, 33))[0][3] == 1
    with pytest.raises(ValueError):
        x.encode_record(b"short", 1, x.STATE_DISPLAYED, 0)
    with pytest.raises(ValueError):
        x.encode_record(item.bytes[:8], 1, 7, 0)


def test_torn_tail_is_ignored():
    item = uuid.uuid4()
    raw = _rec(item, 5, x.STATE_DISPLAYED, 0) + b"\x01\x02\x03"
    assert len(x.decode(raw)) == 1


def test_highest_state_wins_and_latest_minute_is_kept():
    item = uuid.uuid4()
    raw = (
        _rec(item, 100, x.STATE_DISPLAYED, 3)
        + _rec(item, 101, x.STATE_CONSUMED, 3, dwell_only=True)
        + _rec(item, 102, x.STATE_SKIPPED, 3)  # a later lower state never downgrades
    )
    f = x.fold(raw, 3)[item.bytes[:8]]
    assert (f.state, f.minute, f.exposures, f.in_visit) == (x.STATE_CONSUMED, 102, 1, True)
    assert f.dwell_only is True


def test_dwell_only_is_lost_to_any_other_consumption():
    item = uuid.uuid4()
    raw = _rec(item, 1, x.STATE_CONSUMED, 0, dwell_only=True) + _rec(item, 2, x.STATE_CONSUMED, 0)
    assert x.fold(raw, 0)[item.bytes[:8]].dwell_only is False


def test_reload_duplicate_is_one_exposure_and_distinct_visits_cap_at_two():
    item = uuid.uuid4()
    p = item.bytes[:8]
    same_visit = _rec(item, 10, x.STATE_DISPLAYED, 4) * 3  # reload, second tab
    assert x.fold(same_visit, 4)[p].exposures == 1
    two = same_visit + _rec(item, 900, x.STATE_DISPLAYED, 5)
    assert x.fold(two, 5)[p].exposures == 2
    many = two + _rec(item, 2000, x.STATE_DISPLAYED, 6) + _rec(item, 3000, x.STATE_VIEWED, 7)
    assert x.fold(many, 7)[p].exposures == 2  # capped


def test_in_visit_follows_the_current_visit():
    item = uuid.uuid4()
    raw = _rec(item, 10, x.STATE_DISPLAYED, 4)
    p = item.bytes[:8]
    assert x.fold(raw, 4)[p].in_visit is True
    assert x.fold(raw, 5)[p].in_visit is False
    assert x.fold(raw, None)[p].in_visit is False
    assert x.fold(raw, 36)[p].in_visit is True  # 36 mod 32


def test_compaction_keeps_state_count_and_in_visit_with_high_visit_bits():
    """The "two or more" flag lives in bit 31 of the minute word, not in the visit
    bits: a visit_ord with bit 4 set (>= 16) keeps ``in_visit`` exact."""
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    raw = (
        _rec(a, 10, x.STATE_DISPLAYED, 17)
        + _rec(a, 20, x.STATE_VIEWED, 18)  # two visits
        + _rec(b, 30, x.STATE_CONSUMED, 18, dwell_only=True)  # one visit
        + _rec(c, 40, x.STATE_SKIPPED, 2)
    )
    before = x.fold(raw, 18)
    packed = x.compact(raw, cap=200)
    assert len(packed) == 3 * x.RECORD_BYTES
    after = x.fold(packed, 18)
    assert after == before
    assert after[a.bytes[:8]].exposures == 2 and after[a.bytes[:8]].in_visit is True
    assert after[c.bytes[:8]].in_visit is False
    # Appending to a compacted log still counts visits correctly.
    more = packed + _rec(b, 50, x.STATE_DISPLAYED, 19)
    assert x.fold(more, 19)[b.bytes[:8]].exposures == 2
    assert x.fold(packed + _rec(b, 50, x.STATE_DISPLAYED, 18), 18)[b.bytes[:8]].exposures == 1
    # The flag never reads as a minute.
    (word,) = struct.unpack(">I", packed[8:12])
    assert word & 0x8000_0000 and x.decode(packed)[0][1] == 20


def test_compaction_keeps_the_cap_most_recent_items():
    items = [uuid.uuid4() for _ in range(450)]
    raw = b"".join(_rec(it, 1000 + i, x.STATE_DISPLAYED, 1) for i, it in enumerate(items))
    packed = x.compact(raw, cap=200)
    assert len(packed) == 200 * 13 == 2600  # <= 2.6 KB at cap 200
    kept = set(x.fold(packed, 1))
    assert kept == {it.bytes[:8] for it in items[-200:]}


def test_prefix_collision_is_harmless():
    """Two items sharing a 64-bit prefix fold into one entry: at worst one extra
    demotion, never an error."""
    a = uuid.UUID("11111111-2222-3333-4444-555555555555")
    b = uuid.UUID("11111111-2222-3333-9999-999999999999")
    assert x.item_prefix(a) == x.item_prefix(b)
    raw = _rec(a, 1, x.STATE_DISPLAYED, 0) + _rec(b, 2, x.STATE_CONSUMED, 0)
    folded = x.fold(raw, 0)
    assert len(folded) == 1 and folded[x.item_prefix(a)].state == x.STATE_CONSUMED


def test_dwell_states_follow_the_config_thresholds():
    th = x.Thresholds(
        cap=200,
        ttl_s=36 * 3600,
        skip_dwell_ms=1500,
        viewed_dwell_ms=3000,
        consumed_dwell_ms=8000,
        length_buckets=({"max_chars": 280, "scale": 0.75}, {"max_chars": 10**6, "scale": 1.5}),
    )
    assert th.dwell_state(1000, None) == (x.STATE_SKIPPED, False)
    assert th.dwell_state(2000, None) == (x.STATE_DISPLAYED, False)
    assert th.dwell_state(3000, None) == (x.STATE_VIEWED, False)
    assert th.dwell_state(8000, 0) == (x.STATE_CONSUMED, True)  # unknown bucket: unscaled
    assert th.dwell_state(6000, 1) == (x.STATE_CONSUMED, True)  # short excerpt: 0.75 x 8 s
    assert th.dwell_state(11_000, 2) == (x.STATE_VIEWED, False)  # long excerpt needs 12 s
    assert th.dwell_state(12_000, 2) == (x.STATE_CONSUMED, True)
    assert th.max_bytes == 5200


def test_thresholds_come_from_the_config(db):
    from intel import config

    th = x.thresholds(config.for_surface("home"))
    cfg = config.for_surface("home")
    assert th.cap == cfg.get("exposure.ledger.cap")
    assert th.ttl_s == cfg.get("exposure.ledger.ttl_h") * 3600
    assert th.consumed_dwell_ms == cfg.get("exposure.consumed_dwell_ms")
    assert list(th.length_buckets) == cfg.get("exposure.length_buckets")


def test_compaction_keeps_the_latest_appends_within_one_minute():
    items = [uuid.uuid4() for _ in range(300)]
    raw = b"".join(_rec(it, 1000, x.STATE_DISPLAYED, 1) for it in items)  # one minute
    kept = set(x.fold(x.compact(raw, cap=200), 1))
    assert kept == {it.bytes[:8] for it in items[-200:]}
