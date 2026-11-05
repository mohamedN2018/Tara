"""Account deletion for Tara Intelligence (WP 2.10, 03 section 5).

One path, ``erase_account``, run by the ``account.deleted`` handler. It deletes
every ``intel_*`` row keyed by the account (raw partitions included: a ``DELETE``
on the partitioned parent reaches every partition), the account's ``redis-hot``
keys (``feed:rank:*`` sessions, ``intel:prof``), and its posts from every
``intel:pool:*`` sorted set at once (``ZREM`` by post id), not at the next rebuild.

``ACCOUNT_TABLES`` must name every intel table; ``test_account_deletion`` fails
when a new intel model is neither listed here nor in ``NOT_ACCOUNT_KEYED``.
Later work packages add their tables (``intel_experiment_exposure``,
``intel_debug_consent``, ``intel_account_restriction``, ...) to this list.
"""

from __future__ import annotations

import uuid

from django.db import connection, transaction

from . import hot, origin, ports

# (table, WHERE clause with one %(a)s placeholder per use of the account id)
ACCOUNT_TABLES: tuple[tuple[str, str], ...] = (
    # The account's own rows, and other viewers' rows that name its profile or page
    # (a visit, a follow, a mute or a block of it).
    (
        "intel_signal_event",
        "account_id = %(a)s OR (item_type IN ('profile', 'page') AND item_id = %(a)s)",
    ),
    ("intel_user_item_engagement", "account_id = %(a)s OR item_id = %(a)s"),
    ("intel_signal_batch", "account_id = %(a)s"),
    ("intel_synthetic_account", "account_id = %(a)s"),
)
# Intel tables that hold no account data (configs, topics, aggregates without ids).
NOT_ACCOUNT_KEYED: frozenset[str] = frozenset()


def erase_account(account_id) -> dict:
    account = str(uuid.UUID(str(account_id)))
    counts: dict[str, int] = {}
    with transaction.atomic(), connection.cursor() as cur:
        for table, where in ACCOUNT_TABLES:
            cur.execute(f"DELETE FROM {table} WHERE {where}", {"a": account})  # noqa: S608
            counts[table] = cur.rowcount
    origin.clear_cache()
    counts.update(hot.forget_account(account, ports.post_ids_by_author(account)))
    return counts
