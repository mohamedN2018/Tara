"""Moderation intake for spam and sexual hides (04 WP 7.4).

When a viewer hides a post as ``spam`` or ``sexual``, feed recounts that post: the
distinct hiding accounts with that reason over its reach (fan-out recipients). When at
least ``integrity.flag_min_accounts`` accounts hid it and the rate reaches
``integrity.spam_flag_rate_threshold``, feed emits ``intel.integrity.flagged.v1``
(``post_id``, ``author_id``, ``signal``, ``rate``, ``distinct_accounts``: no hider is
named), at most once per post and signal per ``integrity.flag_cooldown_h`` hours
(``intel_integrity_flag``), in the hide's transaction. Feed never emits ``post.*``;
moderation opens or joins a system-sourced case (R4 track B). Behind
``INTEL_EMIT_R4_EVENTS``.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import config, metrics

SIGNALS = {"spam": "spam_hides", "sexual": "sexual_hides"}


def check(post_id, author_id, reason: str, *, now=None) -> bool:
    """Recount and emit when the threshold is crossed. True when an event went out."""
    signal = SIGNALS.get(str(reason))
    if signal is None or not author_id or not getattr(settings, "INTEL_EMIT_R4_EVENTS", True):
        return False
    now = now or timezone.now()
    block = config.for_surface("home").section("integrity")
    with connection.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(DISTINCT account_id) FROM post_hide WHERE post_id = %s "
            "AND reason = %s), (SELECT count(*) FROM feed_item WHERE post_id = %s), "
            "(SELECT flagged_at FROM intel_integrity_flag WHERE post_id = %s AND signal = %s)",
            [str(post_id), reason, str(post_id), str(post_id), signal],
        )
        distinct, reach, last = cur.fetchone()
        rate = min(distinct / max(reach, 1), 1.0)
        if distinct < block["flag_min_accounts"] or rate < block["spam_flag_rate_threshold"]:
            return False
        if last is not None and last > now - timedelta(hours=block["flag_cooldown_h"]):
            return False
        cur.execute(
            "INSERT INTO intel_integrity_flag (post_id, signal, author_id, rate, "
            "distinct_accounts, flagged_at) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (post_id, signal) DO UPDATE SET rate = EXCLUDED.rate, "
            "distinct_accounts = EXCLUDED.distinct_accounts, flagged_at = EXCLUDED.flagged_at",
            [str(post_id), signal, str(author_id), rate, distinct, now],
        )
    from feed.events import PRODUCER
    from feed.models import OutboxEvent

    from tara_events.envelope import EventEnvelope
    from tara_events.outbox import record_event

    record_event(
        OutboxEvent,
        EventEnvelope(
            event_type="intel.integrity.flagged",
            payload={
                "post_id": str(post_id),
                "author_id": str(author_id),
                "signal": signal,
                "rate": round(rate, 6),
                "distinct_accounts": int(distinct),
            },
            subject_id=str(post_id),
            producer=PRODUCER,
            partition_key=f"post:{post_id}",
        ),
    )
    metrics.integrity_flagged(signal)
    return True
