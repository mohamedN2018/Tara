"""Search-text normalisation for listings (Arabic-aware).

Roadmap D6 puts one shared normaliser in ``libs/tara_common`` (milestone 1.8).
Until it lands, marketplace keeps this local copy; swap the import when it does.
The stored ``search_text`` and every query go through the same function, so the
trigram index matches ``اسكندريه`` against ``الإسكندرية``.
"""

from __future__ import annotations

import re
import unicodedata

_TASHKEEL = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_FOLD = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ة": "ه",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        # Eastern Arabic and Persian digits -> ASCII.
        **{chr(0x0660 + i): str(i) for i in range(10)},
        **{chr(0x06F0 + i): str(i) for i in range(10)},
    }
)
_SPACES = re.compile(r"\s+")


def normalise(text: str | None) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    value = _TASHKEEL.sub("", value).replace(_TATWEEL, "")
    value = value.translate(_FOLD).casefold()
    return _SPACES.sub(" ", value).strip()


def search_text(title: str, description: str) -> str:
    # Capped so a long description cannot bloat the trigram index.
    return normalise(f"{title} {description}")[:2000]
