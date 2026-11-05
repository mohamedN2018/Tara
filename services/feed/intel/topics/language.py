"""Content language of a post, from its letters (02 section 8.4, 14). No model, no AI.

Rules, in order, over the letters of the text (digits, punctuation, emoji, URLs,
mentions and hashtags do not count):

- fewer than ``MIN_LETTERS`` letters: ``und``;
- Arabic letters >= 60 %: ``ar``;
- Latin letters >= 60 %: ``en``;
- Arabic >= 25 % and Latin >= 25 %: ``mixed``;
- anything else (another script): ``und``.

Arabizi (Arabic written in Latin letters and digits, "ana 3ayez a7ki") is Latin
text, so it is ``en`` (or ``mixed`` next to Arabic letters), never ``ar``. Other
Latin-script languages (French, ...) are ``en`` too. Both are known, documented
limits of a letters-only rule (04 WP 3.1, 02 section 14; ``test_language.py``).

These thresholds define what is stored, so they are code constants stamped with
``CLASSIFIER_VERSION`` (02 section 8.4), not ranking config: changing one is a code
change with a backfill.
"""

from __future__ import annotations

import re
import unicodedata

CLASSIFIER_VERSION = 1
LANGS = ("ar", "en", "mixed", "und")

MIN_LETTERS = 8
DOMINANT_SHARE = 0.60
MIXED_SHARE = 0.25

_NOISE = re.compile(r"https?://\S+|www\.\S+|[@#][\w؀-ۿ]+", re.UNICODE)


def _is_arabic(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x0600 <= cp <= 0x06FF
        or 0x0750 <= cp <= 0x077F
        or 0x08A0 <= cp <= 0x08FF
        or 0xFB50 <= cp <= 0xFDFF
        or 0xFE70 <= cp <= 0xFEFF
    )


def _is_latin(ch: str) -> bool:
    return ch.isascii() or "LATIN" in unicodedata.name(ch, "")


def detect(text: str | None) -> str:
    """``ar``, ``en``, ``mixed`` or ``und`` for ``text`` (a post's excerpt)."""
    if not text:
        return "und"
    clean = _NOISE.sub(" ", text)
    arabic = latin = letters = 0
    for ch in clean:
        if not ch.isalpha():
            continue
        letters += 1
        if _is_arabic(ch):
            arabic += 1
        elif _is_latin(ch):
            latin += 1
    if letters < MIN_LETTERS:
        return "und"
    ar_share, la_share = arabic / letters, latin / letters
    if ar_share >= DOMINANT_SHARE:
        return "ar"
    if la_share >= DOMINANT_SHARE:
        return "en"
    if ar_share >= MIXED_SHARE and la_share >= MIXED_SHARE:
        return "mixed"
    return "und"
