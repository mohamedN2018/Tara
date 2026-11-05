"""Account restrictions search applies to trending (Tara Intelligence 4b.20-B3).

``moderation.actioned`` on a user with ``restrict`` or ``shadow`` marks the
account; ``reinstate`` lifts it; ``warn``, ``dismiss`` and other targets change
nothing. The same newest-wins rule as feed's ``intel/readmodels.py::
set_restriction``: an event older than the stored one is refused, and a
reinstate seen first is kept as an inactive row so its older restriction,
retried later, is refused too. ``search_backfill_restrictions`` writes through
the same function with the export's clock.

Every change drops the cached trending answers, so a restricted author's posts
stop counting within one request, not after the cache expires.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from django.core.cache import cache
from django.db import transaction

from .models import SearchAccountRestriction

logger = logging.getLogger("tara.search.restrictions")

RESTRICTING_ACTIONS = frozenset({"restrict", "shadow"})
REINSTATE = "reinstate"
TRENDING_CACHE_PREFIX = "search:trending:v2:"
TRENDING_WINDOW_KEYS = ("day", "week")


def trending_cache_key(window: str) -> str:
    return f"{TRENDING_CACHE_PREFIX}{window}"


def _drop_trending_cache() -> None:
    try:
        cache.delete_many([trending_cache_key(w) for w in TRENDING_WINDOW_KEYS])
    except Exception:  # noqa: BLE001 - the cache is an accelerator; it expires anyway
        logger.warning("trending cache invalidation failed", exc_info=True)


def invalidate_trending() -> None:
    """Drop the cached answers now and again after the write commits (a read
    racing the transaction cannot keep a stale answer for the cache's lifetime)."""
    _drop_trending_cache()
    transaction.on_commit(_drop_trending_cache)


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def set_restriction(account_id, action: str, case_id, when: datetime) -> bool:
    """Apply ``restrict`` / ``shadow`` / ``reinstate`` at ``when``; False when
    refused (older than what is stored, or not an account restriction)."""
    account = _uuid(account_id)
    if account is None or action not in (RESTRICTING_ACTIONS | {REINSTATE}):
        return False
    active = action in RESTRICTING_ACTIONS
    with transaction.atomic():
        row = (
            SearchAccountRestriction.objects.select_for_update().filter(account_id=account).first()
        )
        if row is None:
            SearchAccountRestriction.objects.create(
                account_id=account,
                kind=action if active else "",
                active=active,
                case_id=_uuid(case_id),
                event_at=when,
            )
        else:
            if when < row.event_at:
                return False
            if active:
                row.kind, row.case_id = action, _uuid(case_id) or row.case_id
            row.active, row.event_at = active, when
            row.save()
        invalidate_trending()
    return True


def forget(account_id) -> int:
    """``account.deleted``: the account's row goes with it."""
    account = _uuid(account_id)
    if account is None:
        return 0
    deleted, _ = SearchAccountRestriction.objects.filter(account_id=account).delete()
    if deleted:
        invalidate_trending()
    return deleted


def restricted_ids():
    """A subquery of the accounts under an active restriction."""
    return SearchAccountRestriction.objects.filter(active=True).values("account_id")
