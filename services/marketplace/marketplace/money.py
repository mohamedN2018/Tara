"""Listing prices: three price states, an optional sale price, and allowed currencies.

Ported from QTech's ``Product`` (``backend/cms/models.py``), where an empty price
means "on request" and 0 means free. Tara makes the state explicit instead of
reading it off the number, because a number alone could not tell the two apart:

* ``fixed``      a price above zero; an optional sale price below it.
* ``negotiable`` an asking price above zero, or no price at all ("make an offer").
* ``free``       the price is stored as 0, so it sorts first by price.

The price a buyer would pay is ``Coalesce(sale_price, price)``; the database keeps
it in the generated column ``Listing.effective_price`` so sorting and the price
range filter run in SQL.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from tara_common.exceptions import TaraAPIError

# ISO 4217 minor units. Three-decimal currencies must not be rounded to two.
CURRENCY_MINOR_UNITS: dict[str, int] = {
    "EGP": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "SAR": 2,
    "AED": 2,
    "QAR": 2,
    "KWD": 3,
    "BHD": 3,
    "OMR": 3,
    "JOD": 3,
    "IQD": 3,
    "LYD": 3,
    "TND": 3,
    "MAD": 2,
    "DZD": 2,
    "LBP": 2,
    "SDG": 2,
    "TRY": 2,
}
ALLOWED_CURRENCIES = tuple(sorted(CURRENCY_MINOR_UNITS))
DEFAULT_CURRENCY = "USD"

PRICE_TYPES = ("fixed", "negotiable", "free")

# Free-text currencies written before the allow-list, mapped where the meaning is clear.
CURRENCY_ALIASES: dict[str, str] = {
    "LE": "EGP",
    "L.E": "EGP",
    "L.E.": "EGP",
    "EGY": "EGP",
    "ج.م": "EGP",
    "جنيه": "EGP",
    "$": "USD",
    "US$": "USD",
    "€": "EUR",
    "£": "GBP",
    "ر.س": "SAR",
    "ريال": "SAR",
    "د.إ": "AED",
    "درهم": "AED",
    "د.ك": "KWD",
}


def _error(field: str, code: str, message: str) -> TaraAPIError:
    return TaraAPIError(
        message,
        code="validation_error",
        http_status_code=400,
        details=[{"field": field, "code": code, "message": message}],
    )


def normalise_currency(raw: str | None) -> str | None:
    """The allow-listed code for ``raw``, or None when it cannot be mapped."""
    value = (raw or "").strip()
    if not value:
        return None
    upper = value.upper()
    if upper in CURRENCY_MINOR_UNITS:
        return upper
    return CURRENCY_ALIASES.get(upper) or CURRENCY_ALIASES.get(value)


def _decimal(value, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise _error(field, "invalid", "A valid number is required.") from exc
    if not out.is_finite():
        raise _error(field, "invalid", "A valid number is required.")
    return out


def _check_places(amount: Decimal, currency: str, field: str) -> None:
    places = CURRENCY_MINOR_UNITS[currency]
    exponent = amount.normalize().as_tuple().exponent
    if isinstance(exponent, int) and -exponent > places:
        raise _error(
            field,
            "too_many_decimals",
            f"{currency} amounts have at most {places} decimal places.",
        )


def infer_price_type(price: Decimal | None) -> str:
    """What an old client that sends only ``price`` most likely meant."""
    if price is None:
        return "negotiable"
    if price == 0:
        return "free"
    return "fixed"


def resolve_pricing(*, price_type: str | None, price, sale_price, currency: str | None) -> dict:
    """Validate one complete price state; returns the values to store.

    Raises a 400 with a field-level detail for the first rule broken.
    """
    code = normalise_currency(currency) if currency is not None else DEFAULT_CURRENCY
    if code is None or code not in CURRENCY_MINOR_UNITS:
        raise _error("currency", "currency_not_allowed", "This currency is not supported.")

    amount = _decimal(price, "price")
    sale = _decimal(sale_price, "sale_price")
    kind = price_type or infer_price_type(amount)
    if kind not in PRICE_TYPES:
        raise _error("price_type", "invalid_choice", "Unknown price type.")

    if amount is not None and amount < 0:
        raise _error("price", "negative", "Price cannot be negative.")
    if sale is not None and sale < 0:
        raise _error("sale_price", "negative", "Sale price cannot be negative.")

    if kind == "free":
        if amount not in (None, Decimal(0)):
            raise _error("price", "free_has_price", "A free listing has no price.")
        if sale is not None:
            raise _error(
                "sale_price", "sale_price_not_allowed", "A free listing has no sale price."
            )
        amount = Decimal(0)
    elif kind == "fixed":
        if amount is None or amount == 0:
            raise _error("price", "price_required", "A fixed price above zero is required.")
    elif amount is not None and amount == 0:  # negotiable
        raise _error("price", "price_required", "Leave the price empty to take offers.")

    if sale is not None:
        if amount is None:
            raise _error("sale_price", "sale_without_price", "A sale price needs a price.")
        if sale >= amount:
            raise _error(
                "sale_price",
                "sale_price_not_below_price",
                "The sale price must be below the price.",
            )

    for field, value in (("price", amount), ("sale_price", sale)):
        if value is not None:
            _check_places(value, code, field)
            if value >= Decimal(10) ** 15:
                raise _error(field, "too_large", "This amount is too large.")

    return {"price_type": kind, "price": amount, "sale_price": sale, "currency": code}


def effective_price(price: Decimal | None, sale_price: Decimal | None) -> Decimal | None:
    """The same rule as the generated column, for objects not yet re-read."""
    return sale_price if sale_price is not None else price
