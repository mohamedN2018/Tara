"""The opt-in search signal (Tara Intelligence WP 8.7-B2, owner decision 7).

Search history is not an interest signal unless the account opts in, in My
Algorithm. Feed tells search through ``intel.search_signal.changed`` (``enabled`` is
``search_signal`` and not ``personalization_off``); search keeps it in
``search_signal_optin`` (no row = off).

A search reads the state from the cache only (``search:sig:{account}``, written by
the handler with no expiry), so it costs no SQL: the search page keeps its query
budget. A cache that lost the key reads as off, the private direction; the
search-worker beat (``searchsvc.warm_signal_optins``) puts the opted-in accounts back
every 10 minutes from the table, which stays the source of truth.

While it is on, and ``SEARCH_EMIT_QUERY_SIGNALS`` is true, a first-page search emits
``search.queried`` with ``tara_common.signal_terms.term_keys(q)`` only: sha256 digests
of the normalized tokens, at most 8. The query text never leaves search (not in the
event, not in a log).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tara_common.signal_terms import term_keys
from tara_events.envelope import EventEnvelope
from tara_events.outbox import record_event

from .models import OutboxEvent, SearchSignalOptIn

logger = logging.getLogger("tara.search.signals")
PRODUCER = "search-service"


def _key(account_id) -> str:
    return f"search:sig:{account_id}"


def _cache(account_id, enabled: bool) -> None:
    try:
        cache.set(_key(account_id), 1 if enabled else 0, None)
    except Exception:  # noqa: BLE001 - the beat re-warms it; the table is the truth
        logger.warning("search signal state not cached")


def apply_changed(payload: dict) -> bool:
    """Store the newest opt-in state for the account. True when it changed."""
    account_id = payload.get("account_id")
    enabled = payload.get("enabled")
    at = parse_datetime(str(payload.get("at") or ""))
    if not account_id or not isinstance(enabled, bool) or at is None:
        logger.warning("search signal event without account, state or time skipped")
        return False
    with transaction.atomic():
        row, created = SearchSignalOptIn.objects.select_for_update().get_or_create(
            account_id=account_id, defaults={"enabled": enabled, "event_at": at}
        )
        if not created:
            if at <= row.event_at:
                return False
            row.enabled, row.event_at = enabled, at
            row.save(update_fields=["enabled", "event_at", "updated_at"])
        transaction.on_commit(lambda: _cache(account_id, enabled))
    return True


def enabled_for(account_id) -> bool:
    """From the cache only (no SQL on the search path); missing reads as off."""
    try:
        return cache.get(_key(account_id)) == 1
    except Exception:  # noqa: BLE001 - unknown is off (owner decision 7)
        return False


def warm() -> int:
    """Put every opted-in account back in the cache. Returns how many."""
    ids = list(SearchSignalOptIn.objects.filter(enabled=True).values_list("account_id", flat=True))
    for account_id in ids:
        _cache(account_id, True)
    return len(ids)


def record_query(account_id, query: str) -> bool:
    """``search.queried`` for an opted-in account, in its own transaction. Never fails
    the search, and never logs the query."""
    if not account_id or not getattr(settings, "SEARCH_EMIT_QUERY_SIGNALS", True):
        return False
    try:
        if not enabled_for(account_id):
            return False
        keys = term_keys(query)
        if not keys:
            return False
        with transaction.atomic():
            record_event(
                OutboxEvent,
                EventEnvelope(
                    event_type="search.queried",
                    payload={
                        "account_id": str(account_id),
                        "term_keys": keys,
                        "queried_at": timezone.now().isoformat(),
                    },
                    subject_id=str(account_id),
                    producer=PRODUCER,
                    actor_id=str(account_id),
                ),
            )
    except Exception:  # noqa: BLE001 - an opt-in signal never fails a search
        logger.warning("search signal not recorded")
        return False
    return True
