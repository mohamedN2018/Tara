"""Data fixes for the 4.3 price schema, shared by migration 0004 and the commands.

Each function takes the model class so the migration can pass its historical
model. All are idempotent: running them again changes nothing.
"""

from __future__ import annotations

from .money import ALLOWED_CURRENCIES, DEFAULT_CURRENCY, normalise_currency
from .text import search_text


def classify_zero_price_listings(listing_model) -> int:
    """``price=0`` meant either "free" or "on request"; the old schema could not say.

    They become negotiable with no price ("on request") and are flagged, so each
    seller can confirm "free" by editing. Returns how many rows moved.
    """
    return (
        listing_model.objects.filter(price=0, price_unconfirmed=False)
        .exclude(price_type="free")
        .update(price=None, price_type="negotiable", sale_price=None, price_unconfirmed=True)
    )


def normalise_currencies(listing_model) -> tuple[int, int]:
    """Map free-text currencies onto the allow-list; flag the ones that cannot map.

    Returns ``(mapped, flagged)``. A flagged row gets the default currency so the
    check constraint can be validated, and ``currency_unconfirmed`` for review.
    """
    mapped = flagged = 0
    raw_values = (
        listing_model.objects.exclude(currency__in=ALLOWED_CURRENCIES)
        .values_list("currency", flat=True)
        .distinct()
    )
    for raw in list(raw_values):
        code = normalise_currency(raw)
        rows = listing_model.objects.filter(currency=raw)
        if code:
            mapped += rows.update(currency=code)
        else:
            flagged += rows.update(currency=DEFAULT_CURRENCY, currency_unconfirmed=True)
    return mapped, flagged


def backfill_search_text(listing_model, batch_size: int = 500) -> int:
    done = 0
    batch = []
    rows = listing_model.objects.filter(search_text="").only("id", "title", "description")
    for row in rows.iterator(chunk_size=batch_size):
        row.search_text = search_text(row.title, row.description)
        batch.append(row)
        if len(batch) >= batch_size:
            listing_model.objects.bulk_update(batch, ["search_text"])
            done += len(batch)
            batch = []
    if batch:
        listing_model.objects.bulk_update(batch, ["search_text"])
        done += len(batch)
    return done
