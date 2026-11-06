"""The author age class in graph (Tara Intelligence WP 4b.14 graph part, rule E9b;
owner decisions 9b and 37).

One class per account in ``account_ref.age_class``: ``adult``, ``minor`` or
``unknown``, with feed's mapping (``intel/age.py``): adult is ``is_minor`` false
**and** an adult ``age_band``; ``is_minor`` true is a minor; anything else is
unknown. It is taken only from the account's **own** access-token claims when it
calls graph, never from anyone else's request, and no date of birth is stored.

Steady state costs one cache read: a memo (``graph:age:{account}``) holds the class
last written, and the row changes only when the class does. A failure never fails
the request.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger("tara.graph.age")

ADULT, MINOR, UNKNOWN = "adult", "minor", "unknown"
ADULT_BANDS = frozenset({"18-24", "25-34", "35-44", "45+"})  # identity/age.py, as feed
MEMO_TTL_S = 7 * 24 * 3600


def class_of(claims: dict | None) -> str:
    claims = claims or {}
    is_minor = claims.get("is_minor")
    if is_minor is True:
        return MINOR
    if is_minor is False and claims.get("age_band") in ADULT_BANDS:
        return ADULT
    return UNKNOWN


def is_minor_viewer(claims: dict | None) -> bool:
    """Owner decision 9(a): a minor viewer gets no people suggestions."""
    return (claims or {}).get("is_minor") is True


def _memo_key(account_id) -> str:
    return f"graph:age:{account_id}"


def store(account_id, age_class: str) -> bool:
    """Write ``age_class`` for ``account_id`` when it differs. True when a row changed."""
    from .models import AccountRef

    row, created = AccountRef.objects.get_or_create(
        account_id=account_id, defaults={"age_class": age_class}
    )
    if created:
        return True
    if row.age_class == age_class:
        return False
    return bool(
        AccountRef.objects.filter(account_id=account_id)
        .exclude(age_class=age_class)
        .update(age_class=age_class)
    )


def capture(account_id, claims: dict | None) -> str | None:
    if not account_id:
        return None
    age_class = class_of(claims)
    try:
        if cache.get(_memo_key(account_id)) == age_class:
            return age_class
        with transaction.atomic():
            store(account_id, age_class)
        cache.set(_memo_key(account_id), age_class, MEMO_TTL_S)
    except Exception:  # noqa: BLE001 - safety data, but never at the cost of the request
        logger.warning("author age class not stored", exc_info=True)
        return None
    return age_class


class AgeClassMiddleware:
    """After an authenticated request, record the caller's own age class."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        claims = getattr(user, "claims", None)
        if isinstance(claims, dict) and claims.get("type") == "access":
            capture(getattr(user, "account_id", None), claims)
        return response
