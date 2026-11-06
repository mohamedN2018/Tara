"""Nightly retention of the My Algorithm logs (03 section 2.4; R4): preference changes
after ``retention.preference_change_d`` (180), feedback actions after ``feedback_d``
(365), debug consents after ``debug_consent_d`` (90). One ``DELETE`` each."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db import connection
from django.utils import timezone

_TABLES = (
    ("intel_preference_change", "created_at", "preference_change_d"),
    ("intel_feedback_action", "created_at", "feedback_d"),
    ("intel_debug_consent", "granted_at", "debug_consent_d"),
)


def purge(cfg, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    block = cfg.section("retention")
    out = {}
    with connection.cursor() as cur:
        for table, column, key in _TABLES:
            cutoff = now - timedelta(days=int(block[key]))
            cur.execute(f"DELETE FROM {table} WHERE {column} < %s", [cutoff])  # noqa: S608
            out[table] = cur.rowcount
    return out
