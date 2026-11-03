"""Counters for admin's platform statistics (``GET /internal/v1/stats/``, 8.11)."""

from __future__ import annotations

from .models import Account


def count_accounts() -> int:
    """Accounts that exist for members: everything not deleted."""
    return Account.objects.exclude(status=Account.Status.DELETED).count()


COUNTERS = {"accounts": count_accounts}
