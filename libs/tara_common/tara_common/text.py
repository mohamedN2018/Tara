"""One Arabic-aware text normaliser for search (roadmap decision D6).

Every service that searches text stores ``normalize_ar(text)`` in a ``*_norm``
column and runs the query through the same function, so spelling variants
meet: ``اسكندريه`` finds ``الإسكندرية`` and ``احمد`` finds ``أحمد``.

Steps, in order:
- NFKC, so Arabic presentation forms and full-width Latin become plain letters;
- zero-width and bidi control characters are removed (they hide inside names);
- diacritics (harakat, Quranic marks, superscript alef) and tatweel are removed;
- alef variants (أ إ آ ٱ) become ا, ى and ئ become ي, ؤ becomes و, ة becomes ه,
  Persian ی and ک become ي and ك;
- Arabic-Indic and Persian digits become ASCII digits;
- the text is case-folded and runs of whitespace collapse to one space.

``normalize_key`` is the variant for skill and tag keys: it also drops
punctuation, but keeps ``+ # . / -`` so C, C# and C++ stay distinct.
"""

from __future__ import annotations

import re
import unicodedata

# Harakat, Quranic annotation marks, superscript alef, tatweel.
_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
# Zero-width space/joiners, LRM/RLM, ALM, bidi embeddings/isolates, BOM.
_INVISIBLE = re.compile("[​-‏؜‪-‮⁦-⁩﻿]")
_FOLD = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ئ": "ي",
        "ی": "ي",  # Persian yeh
        "ؤ": "و",
        "ة": "ه",
        "ک": "ك",  # Persian keheh
        **{chr(0x0660 + i): str(i) for i in range(10)},  # Arabic-Indic digits
        **{chr(0x06F0 + i): str(i) for i in range(10)},  # Extended (Persian) digits
    }
)
_SPACES = re.compile(r"\s+")
_KEY_PUNCT = re.compile(r"[^\w\s+#./-]")


def normalize_ar(text: str | None) -> str:
    """Search form of ``text``: see the module docstring. ``None`` gives ``""``."""
    if not text:
        return ""
    value = unicodedata.normalize("NFKC", text)
    value = _INVISIBLE.sub("", value)
    value = _DIACRITICS.sub("", value)
    value = value.translate(_FOLD).casefold()
    return _SPACES.sub(" ", value).strip()


def normalize_key(text: str | None) -> str:
    """``normalize_ar`` for skill/tag keys: other punctuation goes, ``+ # . / -`` stay."""
    return _SPACES.sub(" ", _KEY_PUNCT.sub(" ", normalize_ar(text))).strip()


# British spelling, used by marketplace.
normalise = normalize_ar
