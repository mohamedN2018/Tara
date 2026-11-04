"""Self-declared age (roadmap 2.12, decision D12).

The date of birth stays in identity. What leaves it is two access-token claims:
``is_minor`` and ``age_band`` (``unknown`` when no date was given, as for
accounts created before 2.12). A birthday that crosses a band takes effect at
the next token refresh. Consumers must treat ``unknown`` as "not known to be
an adult" for anything age-restricted (roadmap 6.10).
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone

ADULT_AGE = 18
# Upper bound of a plausible self-declared age: older dates are typing mistakes.
MAX_AGE = 120
UNKNOWN_BAND = "unknown"
# (lowest age, band). Coarse on purpose: the token is readable by every service.
_BANDS = ((45, "45+"), (35, "35-44"), (25, "25-34"), (18, "18-24"), (0, "13-17"))


def today() -> date:
    return timezone.localdate()


def age_on(date_of_birth: date, on: date | None = None) -> int:
    """Whole years. A 29 February birthday counts from 1 March in other years."""
    on = on or today()
    before_birthday = (on.month, on.day) < (date_of_birth.month, date_of_birth.day)
    return on.year - date_of_birth.year - int(before_birthday)


def is_minor(date_of_birth: date | None, on: date | None = None) -> bool:
    """False when unknown: read ``age_band`` to tell "adult" from "not known"."""
    return date_of_birth is not None and age_on(date_of_birth, on) < ADULT_AGE


def age_band(date_of_birth: date | None, on: date | None = None) -> str:
    if date_of_birth is None:
        return UNKNOWN_BAND
    age = age_on(date_of_birth, on)
    return next(band for lowest, band in _BANDS if age >= lowest)
