"""Factor codes: which terms of the value model moved an item (02 sections 6.4, 20).

The scorer records each term's contribution; the top three by size travel in the
ranking session (one byte code + one signed byte of contribution, quantized to
``1 / QUANTUM``) and can be turned into "Why am I seeing this?" sentences (WP 4.8).
Integrity terms are recorded too but are **never shown** to anyone: detector names
do not leave the ranking (02 section 20).

Codes are part of the session wire format: append only, never reorder.
"""

from __future__ import annotations

FACTORS = (
    "",  # 0: none
    "freshness",
    "reason",
    "favorite",
    "affinity",
    "dislike",
    "shared_groups",
    "conversation",
    "engagement",
    "s_meaningful",
    "s_like",
    "s_comment",
    "s_share",
    "s_save",
    "s_complete",
    "interest",
    "quality",
    "originality",
    "negative",
    "pending_reports",
    "duplicate",
    "bait",
    "spam_flags",
    # R3 (06 sections 5.3 and 6.2): the exposure multiplier, the new-since boost, the
    # conversation exception. Not mapped by ``why`` yet, so never shown.
    "exposure",
    "new_since_visit",
    "rec_new_activity",
)
CODE = {name: i for i, name in enumerate(FACTORS)}
# Never explained to a viewer (integrity detectors).
HIDDEN = frozenset({"pending_reports", "duplicate", "bait", "spam_flags"})
QUANTUM = 10  # contribution stored as round(value * 10) in a signed byte


def quantize(value: float) -> int:
    return max(-127, min(127, round(value * QUANTUM)))


def top(contributions: list[tuple[str, float]], n: int = 3) -> list[tuple[int, int]]:
    """``[(code, quantized contribution)]`` of the ``n`` largest terms (by size, then
    by code for a stable order), zero terms left out."""
    ranked = sorted(
        ((name, v) for name, v in contributions if v),
        key=lambda t: (-abs(t[1]), CODE[t[0]]),
    )
    return [(CODE[name], quantize(v)) for name, v in ranked[:n]]


def visible(factors: list[tuple[int, int]]) -> list[tuple[str, float]]:
    """Decoded factors a viewer may be shown (integrity detectors removed)."""
    out = []
    for code, q in factors:
        name = FACTORS[code] if 0 < code < len(FACTORS) else ""
        if name and name not in HIDDEN:
            out.append((name, q / QUANTUM))
    return out
