"""Counters for admin's platform statistics (``GET /internal/v1/stats/``, 8.11)."""

from __future__ import annotations

from django.db.models import Q

from .models import ModerationCase
from .services import OPEN_STATES


def count_open_cases() -> int:
    """Cases still waiting for a decision: open or in review."""
    return ModerationCase.objects.filter(state__in=OPEN_STATES).count()


COUNTERS = {"open_cases": count_open_cases}


def count_open_cases_about(account_id) -> int:
    """Open cases about one account or its content, for admin's user console (8.6)."""
    return (
        ModerationCase.objects.filter(state__in=OPEN_STATES)
        .filter(Q(owner_id=account_id) | Q(target_type="user", target_id=str(account_id)))
        .count()
    )


ACCOUNT_COUNTERS = {"open_cases": count_open_cases_about}
