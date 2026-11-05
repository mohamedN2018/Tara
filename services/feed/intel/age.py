"""The author age class (07 WP 4b.14, rule E9b; owner decisions 9b and 37).

One class per account in ``author_ref.age_class``: ``adult``, ``minor`` or ``unknown``.
It is taken only from the account's **own** access-token claims (``is_minor``,
``age_band``: ``identity/tokens.py``) when it makes an authenticated feed request,
with the same mapping as ``eligibility.Viewer.limited``: an adult is ``is_minor``
false **and** an adult age band; ``is_minor`` true is a minor; anything else
(missing claims, an ``unknown`` band) is unknown. No date of birth is stored.

It is safety data, so it is captured whether or not personalization is on. Steady
state costs no SQL: a ``redis-hot`` memo (``intel:age:{account}``) holds the class
last written, and the row is updated only when the class changes. A failure to
write (memo or row) never fails the feed request.
"""

from __future__ import annotations

import logging

from django.db import transaction

from . import hot
from .eligibility import ADULT_BANDS

logger = logging.getLogger("tara.intel.age")

ADULT, MINOR, UNKNOWN = "adult", "minor", "unknown"
CLASSES = (ADULT, MINOR, UNKNOWN)
# The memo only saves a write; losing it costs one conditional UPDATE. A week keeps
# active accounts at zero writes without holding memory for idle ones.
MEMO_TTL_S = 7 * 24 * 3600


def class_of(claims: dict | None) -> str:
    claims = claims or {}
    is_minor = claims.get("is_minor")
    if is_minor is True:
        return MINOR
    if is_minor is False and claims.get("age_band") in ADULT_BANDS:
        return ADULT
    return UNKNOWN


def store(account_id, age_class: str) -> bool:
    """Write ``age_class`` for ``account_id`` when it differs. True when a row changed."""
    from feed.models import AuthorRef

    from .readmodels import EPOCH

    if age_class not in CLASSES:
        raise ValueError(age_class)
    current = (
        AuthorRef.objects.filter(account_id=account_id).values_list("age_class", flat=True).first()
    )
    if current == age_class:
        return False
    if current is None:
        _row, created = AuthorRef.objects.get_or_create(
            account_id=account_id, defaults={"occurred_at": EPOCH, "age_class": age_class}
        )
        if created:
            return True
    return bool(
        AuthorRef.objects.filter(account_id=account_id)
        .exclude(age_class=age_class)
        .update(age_class=age_class)
    )


def capture(account_id, claims: dict | None) -> str | None:
    """Record the requesting account's class from its own claims (fail-soft)."""
    if not account_id:
        return None
    age_class = class_of(claims)
    name = hot.age_key(account_id)
    memo = hot.raw_get(name)
    if memo is not None and memo.decode(errors="ignore") == age_class:
        return age_class
    try:
        with transaction.atomic():
            store(account_id, age_class)
    except Exception:  # noqa: BLE001 - safety data, but never at the cost of the feed
        logger.warning("author age class not stored", exc_info=True)
        return None
    hot.raw_set(name, age_class.encode(), MEMO_TTL_S, "age")
    return age_class
