"""Counters for admin's platform statistics (``GET /internal/v1/stats/``, 8.11)."""

from __future__ import annotations

from .models import Listing


def count_listings() -> int:
    """Listings buyers can see now."""
    return Listing.objects.filter(status=Listing.Status.ACTIVE).count()


COUNTERS = {"listings": count_listings}


def count_listings_by(account_id) -> int:
    """One seller's listings in any state but archived, for admin's user console (8.6)."""
    return (
        Listing.objects.filter(seller_id=account_id).exclude(status=Listing.Status.ARCHIVED).count()
    )


ACCOUNT_COUNTERS = {"listings": count_listings_by}
