"""The interest profile (04 WP 6.3, 6.4, 6.5; 07 WP 6.3-B2, 8.5-B2; 02 section 13).

Rows live in ``intel_user_interest`` (one per account, dim, key, source):

- **explicit** rows (onboarding, My Algorithm, feedback) carry a ``polarity``
  (``like``, ``dislike``, ``more``, ``less``, ``suppressed``, ``muted``, ``hidden``) and
  never decay. ``suppressed`` is the marker a deleted inferred row leaves so it does
  not come straight back; ``muted`` (a topic) and ``hidden`` (a creator) are the
  feedback of 07 WP 7.5-B2.
- **inferred** rows carry three accumulators with lazy decay,
  ``v_now = v x 2^(-dt / half_life)``: short (3 d), mid (14 d), long (45 d), from
  ``interests.half_life_d``. The aggregator (``signals/aggregate.py``) adds
  ``event_weight x topic_confidence`` per event; feedback adds its effect directly.

``interest_rel(item)`` (02 section 13) for ranking::

    inferred(t) = tanh((mix_s*short + mix_m*mid + mix_l*long) / tanh_k)
    explicit(t) = interests.explicit[polarity]          (like 1, more .5, less -.5, dislike -1)
    rel(item)   = clamp(sum_t conf(t) * (explicit_multiplier*explicit(t) + inferred(t))
                        / sum_t conf(t), -1, 1)

**Emerging** (06 section 7, read time, no column): ``short / long >= emerging.ratio``,
``short >= emerging.floor`` and at least ``emerging.min_events`` events.

The ranking profile (top ``profile_top_n`` per dim) is cached in ``intel:prof:{account}``
(``profile_ttl_s``) and dropped on every explicit change. Sensitive topics: no inferred
row is ever written without ``sensitive_inference`` (decision 12; the aggregator and
the feedback service both check it), and explicit rows on them are the user's own.
Under ``personalization_off`` nothing is written or read for ranking.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from django.db import connection, transaction
from django.utils import timezone

from . import hot
from .models import InterestDim, InterestPolarity, UserInterest

EXPLICIT, INFERRED = "explicit", "inferred"
TIERS = ("short", "mid", "long")
NEGATIVE_POLARITIES = frozenset({"dislike", "less", "suppressed", "muted", "hidden"})
DIMS = tuple(InterestDim.values)
POLARITIES = tuple(InterestPolarity.values)
API_POLARITIES = ("like", "dislike", "muted")
PROFILE_CODEC = 1


def decayed(value: float, at: datetime | None, now: datetime, half_life_d: float) -> float:
    if not value or at is None:
        return float(value or 0.0)
    dt_d = max((now - at).total_seconds(), 0.0) / 86400.0
    return float(value) * math.pow(2.0, -dt_d / half_life_d)


def tiers(row, now: datetime, block: dict) -> dict[str, float]:
    """``{short, mid, long}`` of an inferred row, decayed to ``now``."""
    hl = block["half_life_d"]
    return {
        "short": decayed(row.short_v, row.short_at, now, hl["short"]),
        "mid": decayed(row.mid_v, row.mid_at, now, hl["mid"]),
        "long": decayed(row.long_v, row.long_at, now, hl["long"]),
    }


def mixed(t: dict[str, float], block: dict) -> float:
    m = block["tiers_mix"]
    return m["short"] * t["short"] + m["mid"] * t["mid"] + m["long"] * t["long"]


def is_emerging(t: dict[str, float], events: int, block: dict) -> bool:
    """06 section 7: short / long >= ``ratio``, short >= ``floor``, >= ``min_events``.
    The ratio compares the tiers as rates (value / half-life): the raw accumulators
    take the same deltas, so the long one is never below the short one."""
    e = block["emerging"]
    hl = block["half_life_d"]
    short, long = t["short"], t["long"]
    if events < e["min_events"] or short < e["floor"]:
        return False
    long_rate = long / hl["long"]
    return long_rate <= 0 or (short / hl["short"]) / long_rate >= e["ratio"]


def tier_of(t: dict[str, float], events: int, block: dict) -> str:
    """The tier an inferred row is listed under (06 section 10, Manage interests).
    The three accumulators take the same deltas, so the slower ones are always larger;
    each is compared as a rate, ``value / half_life``: the horizon the interest is
    concentrated in (recent activity is short, a few days old medium, steady long)."""
    if mixed(t, block) < 0:
        return "negative"
    if is_emerging(t, events, block):
        return "emerging"
    hl = block["half_life_d"]
    return max(TIERS, key=lambda k: (t[k] / hl[k], -TIERS.index(k)))


# ---- the ranking profile (intel:prof) -------------------------------------------------


@dataclass
class Profile:
    """What ranking reads: per dim ``{key: score}`` where score is the item-level term
    ``explicit_multiplier*explicit + inferred`` of one key, plus the exclusions."""

    topic: dict[int, float] = field(default_factory=dict)
    creator: dict[str, float] = field(default_factory=dict)
    format: dict[str, float] = field(default_factory=dict)
    muted: frozenset[int] = frozenset()
    hidden: frozenset[str] = frozenset()
    disliked_topics: frozenset[int] = frozenset()

    def to_bytes(self) -> bytes:
        return json.dumps(
            {
                "v": PROFILE_CODEC,
                "t": {str(k): round(v, 5) for k, v in self.topic.items()},
                "c": {k: round(v, 5) for k, v in self.creator.items()},
                "f": {k: round(v, 5) for k, v in self.format.items()},
                "m": sorted(self.muted),
                "h": sorted(self.hidden),
                "d": sorted(self.disliked_topics),
            },
            separators=(",", ":"),
        ).encode()

    @classmethod
    def from_bytes(cls, raw: bytes | None) -> Profile | None:
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("v") != PROFILE_CODEC:
            return None
        return cls(
            topic={int(k): float(v) for k, v in data.get("t", {}).items()},
            creator={str(k): float(v) for k, v in data.get("c", {}).items()},
            format={str(k): float(v) for k, v in data.get("f", {}).items()},
            muted=frozenset(int(x) for x in data.get("m", [])),
            hidden=frozenset(str(x) for x in data.get("h", [])),
            disliked_topics=frozenset(int(x) for x in data.get("d", [])),
        )

    @property
    def empty(self) -> bool:
        return not (self.topic or self.creator or self.format)


class _Row:
    """An interest row as the eligibility relations statement returns it."""

    __slots__ = (
        "dim",
        "key",
        "source",
        "polarity",
        "short_v",
        "short_at",
        "mid_v",
        "mid_at",
        "long_v",
        "long_at",
    )

    def __init__(self, dim, key, kind, values):
        from datetime import UTC

        self.dim, self.key = dim, key
        source, _, polarity = (kind or "").partition(":")
        self.source, self.polarity = source, polarity or None
        parts = ((values or "").split("|") + ["0"] * 6)[:6]
        nums = [float(x) if x else 0.0 for x in parts]

        def at(epoch):
            return datetime.fromtimestamp(epoch, UTC) if epoch else None

        self.short_v, self.short_at = nums[0], at(nums[1])
        self.mid_v, self.mid_at = nums[2], at(nums[3])
        self.long_v, self.long_at = nums[4], at(nums[5])


def profile_from_rows(rows, now: datetime, block: dict) -> Profile:
    """The ranking profile from the rows the eligibility statement carried (R4: an
    ``intel:prof`` miss costs no query of its own)."""
    return _profile([_Row(*r) for r in rows], now, block)


def build_profile(account_id, now: datetime, block: dict) -> Profile:
    """The ranking profile from the account's rows (one statement)."""
    rows = list(
        UserInterest.objects.filter(account_id=account_id).only(
            "dim",
            "key",
            "source",
            "polarity",
            "short_v",
            "short_at",
            "mid_v",
            "mid_at",
            "long_v",
            "long_at",
        )
    )
    return _profile(rows, now, block)


def _profile(rows, now: datetime, block: dict) -> Profile:
    k = block["tanh_k"]
    explicit_v, mult = block["explicit"], block["explicit_multiplier"]
    per_dim: dict[str, dict[str, float]] = {"topic": {}, "creator": {}, "format": {}}
    muted, hidden, disliked, suppressed = set(), set(), set(), set()
    for r in rows:
        if r.source == EXPLICIT:
            if r.polarity == "suppressed":
                suppressed.add((r.dim, r.key))
            elif r.polarity == "muted" and r.dim == "topic":
                muted.add(int(r.key))
            elif r.polarity == "hidden" and r.dim == "creator":
                hidden.add(r.key)
    for r in rows:
        if r.dim not in per_dim:
            continue
        if r.source == EXPLICIT:
            value = mult * explicit_v.get(r.polarity or "", 0.0)
            if r.polarity == "dislike" and r.dim == "topic":
                disliked.add(int(r.key))
        else:
            if (r.dim, r.key) in suppressed:
                continue
            value = math.tanh(mixed(tiers(r, now, block), block) / k)
        if value:
            per_dim[r.dim][r.key] = per_dim[r.dim].get(r.key, 0.0) + value
    top = block["profile_top_n"]

    def best(d: dict) -> dict:
        return dict(sorted(d.items(), key=lambda kv: -abs(kv[1]))[:top])

    return Profile(
        topic={int(key): v for key, v in best(per_dim["topic"]).items()},
        creator=best(per_dim["creator"]),
        format=best(per_dim["format"]),
        muted=frozenset(muted),
        hidden=frozenset(hidden),
        disliked_topics=frozenset(disliked),
    )


def store_profile(account_id, profile: Profile, block: dict) -> None:
    hot.raw_set(hot.profile_key(account_id), profile.to_bytes(), block["profile_ttl_s"], "prof")


def cached_profile(account_id, now: datetime, block: dict, raw: bytes | None = None) -> Profile:
    """``intel:prof`` (from the first page's pipelined read when ``raw`` is given),
    else built and stored for ``profile_ttl_s`` (fail-soft)."""
    found = Profile.from_bytes(raw)
    if found is not None:
        return found
    if raw is None:
        found = Profile.from_bytes(hot.raw_get(hot.profile_key(account_id)))
        if found is not None:
            return found
    profile = build_profile(account_id, now, block)
    hot.raw_set(hot.profile_key(account_id), profile.to_bytes(), block["profile_ttl_s"], "prof")
    return profile


def invalidate(account_id) -> None:
    """Drop ``intel:prof`` after an explicit change (fail-soft, and after commit)."""

    def drop():
        try:
            hot.hot().delete_many([hot.profile_key(account_id)])
        except Exception:  # noqa: BLE001 - the TTL bounds the staleness
            from . import metrics

            metrics.hot_purge_failed("prof")

    transaction.on_commit(drop)


def interest_rel(topics: Iterable[tuple[int, float]], profile: Profile) -> float:
    """``rel(item)`` of 02 section 13 over the item's ``(topic_id, confidence)``."""
    num = den = 0.0
    for topic_id, conf in topics:
        den += conf
        num += conf * profile.topic.get(int(topic_id), 0.0)
    if den <= 0:
        return 0.0
    return max(-1.0, min(1.0, num / den))


# ---- writes -----------------------------------------------------------------------------


def snapshot(account_id, keys: Iterable[tuple[str, str]]) -> list[dict]:
    """The exact rows (both sources) of ``(dim, key)`` pairs: an undo restores them."""
    pairs = sorted(set(keys))
    if not pairs:
        return []
    with connection.cursor() as cur:
        cur.execute(
            "SELECT dim, key, source, polarity, short_v, short_at, mid_v, mid_at, long_v, "
            "long_at, events_n, counts, updated_at FROM intel_user_interest "
            "WHERE account_id = %s AND (dim, key) IN "
            "(SELECT * FROM unnest(%s::text[], %s::text[]))",
            [str(account_id), [p[0] for p in pairs], [p[1] for p in pairs]],
        )
        cols = [c.name for c in cur.description]
        out = []
        for row in cur.fetchall():
            item = dict(zip(cols, row, strict=True))
            if isinstance(item["counts"], str):  # the raw cursor returns jsonb as text
                item["counts"] = json.loads(item["counts"])
            for k in ("short_at", "mid_at", "long_at", "updated_at"):
                item[k] = item[k].isoformat() if item[k] else None
            out.append(item)
    return [{"pairs": [list(p) for p in pairs]}, *out]


def restore(account_id, snap: list[dict]) -> None:
    """Put back exactly the rows of ``snapshot`` (delete the pairs, re-insert)."""
    if not snap:
        return
    pairs = snap[0]["pairs"]
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM intel_user_interest WHERE account_id = %s AND (dim, key) IN "
            "(SELECT * FROM unnest(%s::text[], %s::text[]))",
            [str(account_id), [p[0] for p in pairs], [p[1] for p in pairs]],
        )
        for r in snap[1:]:
            cur.execute(
                "INSERT INTO intel_user_interest (account_id, dim, key, source, polarity, "
                "short_v, short_at, mid_v, mid_at, long_v, long_at, events_n, counts, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    str(account_id), r["dim"], r["key"], r["source"], r["polarity"],
                    r["short_v"], r["short_at"], r["mid_v"], r["mid_at"], r["long_v"],
                    r["long_at"], r["events_n"], json.dumps(r["counts"] or {}), r["updated_at"],
                ],
            )  # fmt: skip
    invalidate(account_id)


def add_inferred(
    account_id, dim: str, key: str, delta: float, event: str, now: datetime, block: dict
) -> None:
    """Add ``delta`` to all three tiers of one inferred row (decayed to ``now`` first)."""
    row = (
        UserInterest.objects.select_for_update()
        .filter(account_id=account_id, dim=dim, key=key, source=INFERRED)
        .first()
    )
    if row is None:
        row = UserInterest(
            account_id=account_id, dim=dim, key=key, source=INFERRED, updated_at=now, counts={}
        )
        t = {"short": 0.0, "mid": 0.0, "long": 0.0}
        created = True
    else:
        t = tiers(row, now, block)
        created = False
    row.short_v, row.mid_v, row.long_v = (t[k] + delta for k in TIERS)
    row.short_at = row.mid_at = row.long_at = now
    row.events_n = (row.events_n or 0) + 1
    counts = dict(row.counts or {})
    counts[event] = int(counts.get(event, 0)) + 1
    row.counts = counts
    row.updated_at = now
    if created:
        row.save(force_insert=True)
    else:
        UserInterest.objects.filter(
            account_id=account_id, dim=dim, key=key, source=INFERRED
        ).update(
            short_v=row.short_v,
            mid_v=row.mid_v,
            long_v=row.long_v,
            short_at=now,
            mid_at=now,
            long_at=now,
            events_n=row.events_n,
            counts=counts,
            updated_at=now,
        )


def set_explicit(account_id, dim: str, key: str, polarity: str, now: datetime | None = None):
    now = now or timezone.now()
    UserInterest.objects.update_or_create(
        account_id=account_id,
        dim=dim,
        key=key,
        source=EXPLICIT,
        defaults={"polarity": polarity, "updated_at": now},
    )
    invalidate(account_id)


def remove(account_id, dim: str, key: str, now: datetime | None = None) -> bool:
    """``DELETE /feed/preferences/profile/{dim}/{key}/``: an explicit row goes (an
    unmute, an unhide); an inferred row is deleted and leaves a ``suppressed`` marker
    (02 section 13), so it does not come straight back. False when nothing matched."""
    now = now or timezone.now()
    with transaction.atomic():
        rows = list(
            UserInterest.objects.select_for_update().filter(account_id=account_id, dim=dim, key=key)
        )
        if not rows:
            return False
        explicit = [r for r in rows if r.source == EXPLICIT]
        inferred = [r for r in rows if r.source == INFERRED]
        if explicit and explicit[0].polarity == "suppressed" and not inferred:
            return False
        UserInterest.objects.filter(account_id=account_id, dim=dim, key=key).delete()
        if inferred:
            UserInterest.objects.create(
                account_id=account_id,
                dim=dim,
                key=key,
                source=EXPLICIT,
                polarity="suppressed",
                updated_at=now,
            )
    invalidate(account_id)
    return True


# ---- the owner's view (04 WP 6.4, 07 WP 8.5-B2) --------------------------------------


def _label(dim: str, key: str, topics: dict) -> dict:
    if dim == "topic":
        t = topics.get(int(key)) if key.isdigit() else None
        if t is None:
            return {}
        return {"key": t["slug"], "label_ar": t["label_ar"], "label_en": t["label_en"]}
    return {"key": key}


def profile_view(account_id, now: datetime, block: dict) -> dict:
    """``GET /feed/preferences/profile/``: rows by tier with counts by event type (no
    item ids; a ``post_report`` count is the viewer's own reports, never anyone else's).
    Inferred rows under a ``suppressed`` marker are not listed; muted topics and hidden
    creators are listed apart."""
    from .topics import classify

    topics = classify.load_aliases().topics
    rows = list(UserInterest.objects.filter(account_id=account_id))
    suppressed = {
        (r.dim, r.key) for r in rows if r.source == EXPLICIT and r.polarity == "suppressed"
    }
    ranked: dict[str, list] = {
        t: [] for t in ("explicit", "emerging", "short", "medium", "long", "negative")
    }
    muted, hidden = [], []
    for r in rows:
        labelled = _label(r.dim, r.key, topics)
        if not labelled:
            continue
        item = {
            "dim": r.dim,
            **labelled,
            "source": r.source,
            "counts": {k: int(v) for k, v in (r.counts or {}).items()},
            "updated_at": r.updated_at.isoformat(),
        }
        if r.source == EXPLICIT:
            if r.polarity == "suppressed":
                continue
            item["polarity"] = r.polarity
            if r.polarity == "muted" and r.dim == "topic":
                muted.append(
                    {"slug": labelled["key"], "label_ar": labelled["label_ar"],
                     "label_en": labelled["label_en"]}
                )  # fmt: skip
                continue
            if r.polarity == "hidden" and r.dim == "creator":
                hidden.append({"account_id": r.key, "hidden_at": item["updated_at"]})
                continue
            tier = "negative" if r.polarity in NEGATIVE_POLARITIES else "explicit"
            ranked[tier].append((r.updated_at.timestamp(), item))
            continue
        if (r.dim, r.key) in suppressed:
            continue
        t = tiers(r, now, block)
        tier = tier_of(t, r.events_n, block)
        ranked["medium" if tier == "mid" else tier].append((abs(mixed(t, block)), item))
    cap = block["max_tier_rows"]
    out = {name: [i for _, i in sorted(v, key=lambda x: -x[0])][:cap] for name, v in ranked.items()}
    return {"tiers": out, "muted_topics": muted, "hidden_creators": hidden}
