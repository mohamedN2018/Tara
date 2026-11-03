"""Search normalisation for message text (Arabic-aware).

Ported from QTech's ``core/chatbot.py`` ``_norm``: case-folded, Arabic
diacritics and tatweel removed, alef/ya/ta-marbuta/hamza-seat variants folded,
Arabic-Indic digits mapped to ASCII, whitespace collapsed. The same function
runs on stored bodies (``Message.body_norm``) and on queries, so ``احمد``
finds ``أحمد``.
"""

from __future__ import annotations

import re

# Harakat, Quranic marks, superscript alef and tatweel.
_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_FOLD = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ئ": "ي",
        "ؤ": "و",
        "ة": "ه",
        **{chr(0x0660 + i): str(i) for i in range(10)},  # Arabic-Indic digits
        **{chr(0x06F0 + i): str(i) for i in range(10)},  # Extended (Persian) digits
    }
)
_SPACES = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    if not text:
        return ""
    text = _DIACRITICS.sub("", text.casefold()).translate(_FOLD)
    return _SPACES.sub(" ", text).strip()
