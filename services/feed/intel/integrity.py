"""Quality and integrity signals, deterministic and transparent (02 section 16; WP 4.4).

Written at content time (``intel.readmodels.content_created`` / ``content_updated``,
and the content backfill), from the post's 280-character excerpt, which is never
stored:

- ``simhash``: a 64-bit SimHash of the normalized words and word pairs. Two posts
  are near copies when their Hamming distance is at most
  ``integrity.simhash_max_distance``. A post's ``dup_of`` names the **oldest** live
  near copy by the same author within ``simhash_author_window_days``, or by anyone
  in a public post within ``simhash_public_window_hours``; the oldest copy itself has
  none, so only the later copies are demoted.
- ``bait_score``: hits of the Arabic and English engagement-bait lexicons
  (``topics/lexicons/bait_{ar,en}.txt``), ``1 − 0.5^hits`` (one hit 0.5, two 0.75).
  The precision and recall on a hand-labelled gold set are measured by
  ``tests/test_bait_gold.py`` and reported in ``docs/intelligence/results/phase-04.md``.

And at reaction time (``feed.readmodels.set_reaction``):

- ``suspect_reaction``: a reaction from an account younger than
  ``integrity.suspect_account_age_hours`` or past ``suspect_burst_per_min`` reactions
  in one minute is **excluded from rates** (it never moves ``post_stats`` or
  ``affinity``), never penalized; counted in ``intel_suspect_engagement_total``.

The tokenizer, the hash and the lexicon weighting define what is stored, so they are
code constants stamped with ``CLASSIFIER_VERSION`` (02 section 8.4); every threshold
and multiplier is read from the active home config's ``integrity`` block.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from django.db import connection

from tara_common.text import normalize_ar

from . import config, metrics

logger = logging.getLogger("tara.intel.integrity")

CLASSIFIER_VERSION = 1
_LEXICONS = Path(__file__).resolve().parent / "topics" / "lexicons"
_NOISE = re.compile(r"https?://\S+|www\.\S+|@[\w؀-ۿ.]+", re.UNICODE)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)  # letters and digits, no punctuation
_MASK64 = (1 << 64) - 1


def normalize(text: str | None) -> str:
    """Lower-cased, Arabic-folded words separated by single spaces (no punctuation,
    links or mentions). Hashtags keep their word (``#اعمل_شير`` gives ``اعمل شير``)."""
    if not text:
        return ""
    clean = normalize_ar(_NOISE.sub(" ", text)).replace("_", " ")
    return " ".join(_WORD.findall(clean))


# ---- SimHash ----------------------------------------------------------------------------


def _h64(token: str) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")


def simhash(text: str | None, min_tokens: int) -> int | None:
    """Signed 64-bit SimHash (Postgres ``bigint``) of words and word pairs, or None
    for a text with fewer than ``min_tokens`` words (too short to call a copy)."""
    words = normalize(text).split()
    if len(words) < min_tokens:
        return None
    features = words + [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]
    acc = [0] * 64
    for token in features:
        h = _h64(token)
        for bit in range(64):
            acc[bit] += 1 if (h >> bit) & 1 else -1
    value = sum(1 << bit for bit in range(64) if acc[bit] > 0)
    return value - (1 << 64) if value >= 1 << 63 else value


def hamming(a: int, b: int) -> int:
    return ((a ^ b) & _MASK64).bit_count()


_OLDEST_COPY_SQL = """
SELECT post_id FROM intel_content_ref
WHERE post_id <> %(post)s AND state = 'live' AND simhash IS NOT NULL
  AND (created_at, post_id) < (%(created)s, %(post)s)
  AND ((author_id = %(author)s AND created_at >= %(author_since)s)
       OR (audience = 'public' AND group_id IS NULL AND created_at >= %(public_since)s))
  AND bit_count((simhash # %(hash)s)::bit(64)) <= %(dist)s
ORDER BY created_at, post_id LIMIT 1
"""
# Copies created after this post that did not know an older original (events arrive
# out of order) now point at it.
_LATER_COPIES_SQL = """
UPDATE intel_content_ref SET dup_of = %(post)s
WHERE post_id <> %(post)s AND dup_of IS NULL AND state = 'live' AND simhash IS NOT NULL
  AND (created_at, post_id) > (%(created)s, %(post)s)
  AND ((author_id = %(author)s AND created_at <= %(author_until)s)
       OR (%(public)s AND created_at <= %(public_until)s))
  AND bit_count((simhash # %(hash)s)::bit(64)) <= %(dist)s
"""


def link_duplicates(row) -> None:
    """Set ``row.dup_of`` (an ``intel_content_ref`` row, saved by the caller) to its
    oldest live near copy, and point later copies at ``row``. Needs ``simhash`` and
    ``created_at``; a row without them is no duplicate."""
    if row.simhash is None or row.created_at is None:
        row.dup_of = None
        return
    block = config.for_surface("home").section("integrity")
    author_window = timedelta(days=block["simhash_author_window_days"])
    public_window = timedelta(hours=block["simhash_public_window_hours"])
    params = {
        "post": str(row.post_id),
        "created": row.created_at,
        "author": str(row.author_id) if row.author_id else None,
        "hash": row.simhash,
        "dist": block["simhash_max_distance"],
    }
    with connection.cursor() as cur:
        cur.execute(
            _OLDEST_COPY_SQL,
            {
                **params,
                "author_since": row.created_at - author_window,
                "public_since": row.created_at - public_window,
            },
        )
        found = cur.fetchone()
        row.dup_of = found[0] if found else None
        cur.execute(
            _LATER_COPIES_SQL,
            {
                **params,
                "author_until": row.created_at + author_window,
                "public": row.audience == "public" and row.group_id is None,
                "public_until": row.created_at + public_window,
            },
        )


# ---- engagement bait --------------------------------------------------------------------


@lru_cache(maxsize=1)
def _lexicon() -> tuple[str, ...]:
    phrases: set[str] = set()
    for lang in ("ar", "en"):
        path = _LEXICONS / f"bait_{lang}.txt"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):  # a comment line
                continue
            phrase = normalize(line)
            if phrase:
                phrases.add(phrase)
    return tuple(sorted(phrases, key=len, reverse=True))


def bait_hits(text: str | None) -> list[str]:
    """The lexicon phrases ``text`` contains, as whole words, longest first, without
    counting a phrase that only repeats part of a longer one already found."""
    norm = f" {normalize(text)} "
    if norm.strip() == "":
        return []
    hits: list[str] = []
    for phrase in _lexicon():
        # Arabic attaches "and" (و) to the next word: "ومنشن صاحبك" is "و منشن صاحبك".
        needles = [f" {phrase} "] + ([f" و{phrase} "] if _is_arabic(phrase) else [])
        found = [n for n in needles if n in norm]
        if found:
            hits.append(phrase)
            for n in found:
                norm = norm.replace(n, " | ")
    return hits


def _is_arabic(phrase: str) -> bool:
    return "؀" <= phrase[0] <= "ۿ"


def bait_score(text: str | None) -> float:
    return round(1.0 - 0.5 ** len(bait_hits(text)), 4)


def is_bait(score: float | None, block: dict) -> bool:
    return score is not None and score >= block["bait_min_score"]


# ---- suspect engagement -----------------------------------------------------------------


def suspect_reaction(reactor_id, when: datetime) -> str | None:
    """Why a reaction is excluded from rates (``new_account`` or ``burst``), or None.
    Both rules are off when their threshold is 0 (``home@1``)."""
    from feed.models import AuthorRef, ReactionState

    block = config.for_surface("home").section("integrity")
    age_h, burst = block["suspect_account_age_hours"], block["suspect_burst_per_min"]
    reason = None
    if age_h:
        registered = (
            AuthorRef.objects.filter(account_id=reactor_id)
            .values_list("registered_at", flat=True)
            .first()
        )
        if registered is not None and when - registered < timedelta(hours=age_h):
            reason = "new_account"
    if reason is None and burst:
        recent = ReactionState.objects.filter(
            reactor_id=reactor_id,
            occurred_at__gt=when - timedelta(minutes=1),
            occurred_at__lte=when,
        ).count()
        if recent >= burst:
            reason = "burst"
    if reason:
        metrics.suspect_engagement(reason)
    return reason
