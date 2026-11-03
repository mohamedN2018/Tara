"""Search-text normalisation for listings (Arabic-aware).

The normaliser itself lives in ``tara_common.text`` (roadmap D6); this module
re-exports it so existing imports keep working. The stored ``search_text`` and
every query go through the same function, so the trigram index matches
``اسكندريه`` against ``الإسكندرية``.
"""

from __future__ import annotations

from tara_common.text import normalise, normalize_ar

__all__ = ["normalise", "normalize_ar", "search_text"]


def search_text(title: str, description: str) -> str:
    # Capped so a long description cannot bloat the trigram index.
    return normalise(f"{title} {description}")[:2000]
