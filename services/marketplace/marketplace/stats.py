"""Counters for admin's platform statistics (``GET /internal/v1/stats/``, 8.11)."""

from __future__ import annotations

from .models import Listing


def count_listings() -> int:
    """Listings buyers can see now."""
    return Listing.objects.filter(status=Listing.Status.ACTIVE).count()


COUNTERS = {"listings": count_listings}
