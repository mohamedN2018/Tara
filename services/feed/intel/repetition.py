"""The maths of the repetition harness (07 WP 4b.1), kept pure so it is tested on fixtures.

``manage.py intel_measure_repetition`` collects pages through the real Home view and
hands plain lists to these functions. Nothing here reads the database or Redis, and
nothing returns an account id: only counts, ratios and distributions.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence


def jaccard(a: Iterable, b: Iterable) -> float:
    """|a ∩ b| / |a ∪ b|; two empty lists are identical (1.0)."""
    sa, sb = set(a), set(b)
    union = sa | sb
    if not union:
        return 1.0
    return len(sa & sb) / len(union)


def percentile(values: Sequence[float], q: float) -> float | None:
    """The ``q`` quantile (0..1) by linear interpolation between closest ranks; None
    for an empty list (never an invented number)."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return float(ordered[lo])
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def spread(values: Sequence[float]) -> dict:
    """``{n, min, p10, p50, p90, max}`` of ``values``; empty → n = 0 and nulls."""
    vals = list(values)
    if not vals:
        return {"n": 0, "min": None, "p10": None, "p50": None, "p90": None, "max": None}
    return {
        "n": len(vals),
        "min": min(vals),
        "p10": percentile(vals, 0.10),
        "p50": percentile(vals, 0.50),
        "p90": percentile(vals, 0.90),
        "max": max(vals),
    }


def longest_run(types: Sequence[str]) -> int:
    """The longest run of one value (the format rule of the diversity re-ranker)."""
    best = run = 0
    prev = object()
    for t in types:
        run = run + 1 if t == prev else 1
        prev = t
        best = max(best, run)
    return best


def page_diversity(authors: Sequence[str], types: Sequence[str]) -> dict:
    """Distinct authors, the most items of one author, and the longest format run."""
    counts = Counter(a for a in authors if a)
    return {
        "items": len(authors),
        "distinct_authors": len(counts),
        "max_per_author": max(counts.values()) if counts else 0,
        "longest_format_run": longest_run(types),
    }


def open_overlap(opens: Sequence[Sequence[str]]) -> list[float]:
    """Jaccard of open 1 against each later open (06 §1.1: "open 1 against opens 2 to 4")."""
    if len(opens) < 2:
        return []
    first = opens[0]
    return [jaccard(first, later) for later in opens[1:]]


def arrival_per_day(rows: Iterable[tuple[object, object, int]]) -> dict:
    """``rows`` = ``(recipient, day, n)`` new ``feed_item`` rows per recipient per UTC
    day (the query groups them). Returns the distribution over (recipient, day) pairs
    and over recipients' daily means, so one seed burst cannot pass for steady arrival."""
    per_pair: list[int] = []
    per_recipient: dict[object, list[int]] = {}
    for recipient, _day, n in rows:
        per_pair.append(int(n))
        per_recipient.setdefault(recipient, []).append(int(n))
    means = [sum(v) / len(v) for v in per_recipient.values()]
    return {
        "recipient_days": spread(per_pair),
        "recipient_daily_mean": spread(means),
        "recipients": len(per_recipient),
    }


def gaps_seconds(times_by_account: dict[object, Sequence[float]]) -> list[float]:
    """Gaps between successive visits per account (epoch seconds, any order)."""
    out: list[float] = []
    for times in times_by_account.values():
        ordered = sorted(times)
        out += [b - a for a, b in zip(ordered, ordered[1:], strict=False)]
    return out


def share(part: int, whole: int) -> float | None:
    return None if whole <= 0 else part / whole
