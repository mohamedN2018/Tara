"""Counters for admin's platform statistics (``GET /internal/v1/stats/``, 8.11)."""

from __future__ import annotations

from .models import ModerationCase
from .services import OPEN_STATES


def count_open_cases() -> int:
    """Cases still waiting for a decision: open or in review."""
    return ModerationCase.objects.filter(state__in=OPEN_STATES).count()


COUNTERS = {"open_cases": count_open_cases}
