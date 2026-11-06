"""The interest tiers of the 60 s aggregator (04 WP 6.3; 07 WP 6.3-B2; 02 section 13).

Runs inside ``aggregate.run`` (the same beat job, no second one). Each signal row
received in ``(watermark, hi - OVERLAP]`` adds ``event_weights[type] x confidence`` to
the account's inferred rows, in all three tiers at once (short, mid, long), decayed
lazily to ``hi``:

- a post, reel or video: each of its topics (``intel_content_topic``, x confidence),
  its creator, its format and its language (ar or en);
- a profile or page (follow, unfollow, mute, block, profile visit): the creator only
  (02 section 8.3);
- a group (``group_join`` / ``group_leave``): the group's category (``group_cat``)
  and the topic its category maps to.

A ``feed_dwell`` counts only at or above the consumed threshold stored with the row
(``feed_dwell_consumed``, weight 0.15 = the open weight x the dwell-only 0.3);
impressions weigh 0. Feedback actions are applied by the feedback service in their
own transaction and are skipped here (no double count).

**Exactly once.** The watermark lives in ``intel_aggregate_watermark`` and moves in
the transaction that applies the deltas, and the window ends ``OVERLAP`` before
``hi`` so a batch committed late (within 2 min) is still read once. Re-running a tick
changes nothing.

**Skipped, fail closed:** accounts with ``personalization_off``; rows before the
account's ``reset_at``; synthetic and test actors unless ``INTEL_SYNTHETIC_IN_RANKING``;
sensitive topics without ``sensitive_inference`` (decision 12); rows flagged
``INELIGIBLE_ITEM``. Rows whose three tiers decayed below ``prune_below`` are deleted.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime

from django.conf import settings
from django.db import connection, transaction

from ..models import SignalFlag
from . import partitions

WATERMARK = "interests"
FEEDBACK_TYPES = (
    "interested",
    "not_interested",
    "more_like_this",
    "less_like_this",
    "mute_topic",
    "hide_creator",
)
_POST_KINDS = ("post", "reel", "video")
_LANGS = ("ar", "en")

_SQL = """
SELECT e.account_id, e.event_type, e.item_type, e.item_id, e.author_id, e.watch_ms,
       e.duration_ms, e.received_at, c.type, c.lang,
       COALESCE(p.sensitive_inference, false),
       (SELECT array_agg(t.topic_id || ':' || t.confidence || ':' || CASE WHEN tp.sensitive
               THEN 1 ELSE 0 END ORDER BY t.confidence DESC)
          FROM intel_content_topic t JOIN intel_topic tp ON tp.id = t.topic_id
         WHERE t.post_id = e.item_id),
       g.category,
       (SELECT a.topic_id || ':' || CASE WHEN tp.sensitive THEN 1 ELSE 0 END
          FROM intel_topic_alias a JOIN intel_topic tp ON tp.id = a.topic_id
         WHERE a.kind = 'group_category' AND a.value_norm = g.category AND a.status = 'active'
         LIMIT 1)
FROM intel_signal_event e
LEFT JOIN intel_user_preference p ON p.account_id = e.account_id
LEFT JOIN intel_content_ref c ON c.post_id = e.item_id AND e.item_type = ANY(%(posts)s)
LEFT JOIN intel_group_ref g ON g.group_id = e.item_id AND e.item_type = 'group'
WHERE e.received_at > %(lo)s AND e.received_at <= %(hi)s
  AND e.event_type = ANY(%(types)s)
  AND (%(synthetic)s OR e.data_origin = 'real')
  AND (e.flags & %(ineligible)s) = 0
  AND NOT COALESCE(p.personalization_off, false)
  AND (p.reset_at IS NULL OR e.received_at >= p.reset_at)
"""
_UPSERT = """
INSERT INTO intel_user_interest (account_id, dim, key, source, polarity, short_v, short_at,
    mid_v, mid_at, long_v, long_at, events_n, counts, updated_at)
VALUES (%s, %s, %s, 'inferred', NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (account_id, dim, key, source) DO UPDATE SET
    short_v = EXCLUDED.short_v, short_at = EXCLUDED.short_at, mid_v = EXCLUDED.mid_v,
    mid_at = EXCLUDED.mid_at, long_v = EXCLUDED.long_v, long_at = EXCLUDED.long_at,
    events_n = EXCLUDED.events_n, counts = EXCLUDED.counts, updated_at = EXCLUDED.updated_at
"""


def _decay(value: float, at: datetime | None, now: datetime, half_life_d: float) -> float:
    if not value or at is None:
        return float(value or 0.0)
    return float(value) * math.pow(
        2.0, -max((now - at).total_seconds(), 0.0) / 86400.0 / half_life_d
    )


def _weight_key(event_type: str, watch_ms, duration_ms, consumed_ms: int) -> str | None:
    if event_type == "feed_dwell":
        threshold = duration_ms if duration_ms else consumed_ms
        return "feed_dwell_consumed" if (watch_ms or 0) >= threshold else None
    return event_type


def _parse_topics(raw) -> list[tuple[int, float, bool]]:
    out = []
    for item in raw or []:
        parts = str(item).split(":")
        if len(parts) == 3:
            out.append((int(parts[0]), float(parts[1]), parts[2] == "1"))
    return out


def _watermark(cur, hi: datetime) -> datetime:
    cur.execute("SELECT hi FROM intel_aggregate_watermark WHERE name = %s FOR UPDATE", [WATERMARK])
    row = cur.fetchone()
    if row is not None:
        return row[0]
    return partitions.oldest_kept(partitions.SIGNALS, hi)


def aggregate(hi: datetime, overlap, cfg) -> dict:
    """Apply every row received since the watermark up to ``hi - overlap`` (once)."""
    from .. import exposure

    block = cfg.section("interests")
    weights = block["event_weights"]
    hl = block["half_life_d"]
    consumed_ms = exposure.thresholds(cfg).consumed_dwell_ms
    end = hi - overlap
    types = sorted({k for k in weights if k != "feed_dwell_consumed"} | {"feed_dwell"})
    types = [t for t in types if t not in FEEDBACK_TYPES]
    with transaction.atomic(), connection.cursor() as cur:
        lo = _watermark(cur, hi)
        if end <= lo:
            return {"interest_rows": 0, "events": 0}
        cur.execute(
            _SQL,
            {
                "lo": lo,
                "hi": end,
                "posts": list(_POST_KINDS),
                "types": types,
                "synthetic": bool(settings.INTEL_SYNTHETIC_IN_RANKING),
                "ineligible": SignalFlag.INELIGIBLE_ITEM,
            },
        )
        deltas: dict[tuple[str, str, str], list] = defaultdict(lambda: [0.0, 0, {}, None])
        events = 0
        for (account, etype, itype, item, author, watch, duration, received, ctype, clang,
             sensitive_ok, topics_raw, gcat, gtopic) in cur.fetchall():  # fmt: skip
            key = _weight_key(etype, watch, duration, consumed_ms)
            weight = weights.get(key) if key else None
            if not weight:
                continue
            events += 1
            account = str(account)
            # The delta is decayed from the event time to the end of the window.
            touched = []
            if itype in _POST_KINDS:
                for topic_id, conf, sensitive in _parse_topics(topics_raw):
                    if sensitive and not sensitive_ok:
                        continue
                    touched.append(("topic", str(topic_id), weight * conf))
                if author:
                    touched.append(("creator", str(author), weight))
                if ctype:
                    touched.append(("format", ctype, weight))
                if clang in _LANGS:
                    touched.append(("lang", clang, weight))
            elif itype in ("profile", "page"):
                touched.append(("creator", str(item), weight))
            elif itype == "group" and gcat:
                touched.append(("group_cat", gcat, weight))
                if gtopic:
                    topic_id, _, sens = str(gtopic).partition(":")
                    if sens != "1" or sensitive_ok:
                        touched.append(("topic", topic_id, weight))
            for dim, k, amount in touched:
                entry = deltas[(account, dim, k)]
                entry[0] += amount  # undecayed sum; decayed per tier below
                entry[1] += 1
                entry[2][etype] = entry[2].get(etype, 0) + 1
                entry[3] = max(entry[3] or received, received)
                entry.append((amount, received))
        written = _apply(cur, deltas, end, hl, block["prune_below"])
        cur.execute(
            "INSERT INTO intel_aggregate_watermark (name, hi) VALUES (%s, %s) "
            "ON CONFLICT (name) DO UPDATE SET hi = EXCLUDED.hi",
            [WATERMARK, end],
        )
    return {"interest_rows": written, "events": events}


def _apply(cur, deltas: dict, now: datetime, hl: dict, prune_below: float) -> int:
    if not deltas:
        return 0
    accounts = sorted({a for a, _, _ in deltas})
    cur.execute(
        "SELECT account_id, dim, key, short_v, short_at, mid_v, mid_at, long_v, long_at, "
        "events_n, counts FROM intel_user_interest WHERE source = 'inferred' "
        "AND account_id = ANY(%s::uuid[]) FOR UPDATE",
        [accounts],
    )
    existing = {(str(r[0]), r[1], r[2]): r for r in cur.fetchall()}
    written = 0
    for (account, dim, key), entry in deltas.items():
        n, counts, adds = entry[1], entry[2], entry[4:]
        old = existing.get((account, dim, key))
        tiers = {}
        for i, tier in enumerate(("short", "mid", "long")):
            base = _decay(old[3 + 2 * i], old[4 + 2 * i], now, hl[tier]) if old else 0.0
            tiers[tier] = base + sum(_decay(a, t, now, hl[tier]) for a, t in adds)
        stored = old[10] if old else None
        if isinstance(stored, str):  # Django's raw cursor returns jsonb as text
            stored = json.loads(stored)
        merged = dict(stored or {})
        for etype, c in counts.items():
            merged[etype] = int(merged.get(etype, 0)) + c
        if max(abs(v) for v in tiers.values()) < prune_below:
            cur.execute(
                "DELETE FROM intel_user_interest WHERE account_id = %s AND dim = %s "
                "AND key = %s AND source = 'inferred'",
                [account, dim, key],
            )
            continue
        cur.execute(
            _UPSERT,
            [
                account,
                dim,
                key[:64],
                tiers["short"],
                now,
                tiers["mid"],
                now,
                tiers["long"],
                now,
                (old[9] if old else 0) + n,
                json.dumps(merged),
                now,
            ],
        )
        written += 1
    return written
