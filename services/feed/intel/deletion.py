"""Account deletion for Tara Intelligence (WP 2.10, 03 section 5).

One path, ``erase_account``, run by the ``account.deleted`` handler. It deletes
every ``intel_*`` row keyed by the account (raw partitions included: a ``DELETE``
on the partitioned parent reaches every partition), the account's ``redis-hot``
keys (``feed:rank:*`` sessions, ``intel:prof``), and its posts from every
``intel:pool:*`` sorted set at once (``ZREM`` by post id), not at the next rebuild.

``ACCOUNT_TABLES`` must name every intel table; ``test_account_deletion`` fails
when a new intel model is neither listed here nor in ``NOT_ACCOUNT_KEYED``.
Later work packages add their tables (``intel_experiment_exposure``,
``intel_debug_consent``, ...) to this list.
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
    # Phase 3 read models: the account's posts, edges both ways, memberships,
    # blocks either way and any restriction.
    ("intel_fanout_capped", "author_id = %(a)s"),
    ("intel_content_ref", "author_id = %(a)s"),
    ("intel_friend_edge", "account_id = %(a)s OR friend_id = %(a)s"),
    ("intel_group_membership", "account_id = %(a)s"),
    ("intel_block_pair", "low = %(a)s OR high = %(a)s"),
    ("intel_account_restriction", "account_id = %(a)s"),
    # My Algorithm settings (WP 4.6).
    ("intel_user_preference", "account_id = %(a)s"),
)
# Rows that name the account but belong to something else: the id is cleared, the
# row stays. A page is not its owner's (graph keeps its page refs too); with no
# owner known, rule E4 has no owner to check and E6b still decides on the page.
ACCOUNT_SCRUBS: tuple[tuple[str, str], ...] = (
    ("intel_page_ref", "UPDATE intel_page_ref SET owner_id = NULL WHERE owner_id = %(a)s"),
)
# Intel tables that hold no account data (configs, topics, aggregates without ids).
# The ranking config and its change log (WP 4.1) name only the staff member who made
# a change: an audit record kept forever (03 section 2.7), like admin's AuditEntry.
NOT_ACCOUNT_KEYED: frozenset[str] = frozenset(
    {"intel_media_ref", "intel_group_ref", "intel_ranking_config", "intel_ranking_config_change"}
)


def erase_account(account_id) -> dict:
    account = str(uuid.UUID(str(account_id)))
    counts: dict[str, int] = {}
    # Its posts, from feed's rows and from the content read model (post.deleted
    # may already have removed the feed rows of some of them).
    post_ids = set(ports.post_ids_by_author(account))
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SELECT post_id FROM intel_content_ref WHERE author_id = %s", [account])
        post_ids |= {str(r[0]) for r in cur.fetchall()}
        for table, where in ACCOUNT_TABLES:
            cur.execute(f"DELETE FROM {table} WHERE {where}", {"a": account})  # noqa: S608
            counts[table] = cur.rowcount
        for table, sql in ACCOUNT_SCRUBS:
            cur.execute(sql, {"a": account})
            counts[table] = cur.rowcount
    origin.clear_cache()
    counts.update(hot.forget_account(account, sorted(post_ids)))
    return counts
