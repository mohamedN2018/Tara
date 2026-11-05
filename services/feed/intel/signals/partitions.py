"""Range partitions for the telemetry tables (03 section 2.6, WP 2.2).

- ``intel_signal_event``: one partition per UTC day of ``received_at``, named
  ``intel_signal_event_pYYYYMMDD``. Dropped once the whole day is older than
  ``INTEL_SIGNAL_RETENTION_DAYS`` (30; 90 in dev).
- ``intel_user_item_engagement``: one partition per ISO week (Monday) of
  ``first_at``, named ``intel_user_item_engagement_pYYYYMMDD``. Dropped once the whole
  week is older than ``INTEL_ENGAGEMENT_RETENTION_DAYS`` (30, configurable 7 to 30).
- ``intel_signal_batch``: plain table, rows older than 48 h are deleted.

Partitions are created ``AHEAD_DAYS`` ahead by the beat task (hourly, idempotent);
writers also make sure today's partition exists before writing (``ensure``), so a
stalled beat never makes ingestion fail. Old data is dropped a partition at a time,
never deleted row by row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from django.conf import settings
from django.db import connection, transaction

AHEAD_DAYS = 7
BATCH_RETENTION = timedelta(hours=48)


@dataclass(frozen=True)
class Partitioned:
    table: str
    step_days: int  # 1 = daily, 7 = weekly (Monday-aligned)

    def start_of(self, day: date) -> date:
        return day - timedelta(days=day.weekday()) if self.step_days == 7 else day

    def name(self, start: date) -> str:
        return f"{self.table}_p{start:%Y%m%d}"

    def pattern(self) -> re.Pattern:
        return re.compile(rf"^{re.escape(self.table)}_p(\d{{8}})$")


SIGNALS = Partitioned("intel_signal_event", 1)
ENGAGEMENT = Partitioned("intel_user_item_engagement", 7)
TABLES = (SIGNALS, ENGAGEMENT)

_known: set[str] = set()  # partitions this process has seen exist


def _bounds(spec: Partitioned, start: date) -> tuple[str, str]:
    lo = datetime(start.year, start.month, start.day, tzinfo=UTC)
    return lo.isoformat(), (lo + timedelta(days=spec.step_days)).isoformat()


def _exists(name: str) -> bool:
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", [name])
        return bool(cur.fetchone()[0])


def ensure(spec: Partitioned, day: date) -> str:
    """Create the partition holding ``day`` unless it exists. Returns its name."""
    start = spec.start_of(day)
    name = spec.name(start)
    if name in _known:
        return name
    if _exists(name):
        _known.add(name)
        return name
    lo, hi = _bounds(spec, start)
    with connection.cursor() as cur:
        # Names come from dates only; bounds are ISO timestamps we built.
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF {spec.table} "  # noqa: S608
            f"FOR VALUES FROM ('{lo}') TO ('{hi}')"
        )
    # Remembered only once the CREATE commits: a rolled-back request (or test) must
    # not leave this process believing a partition exists that does not.
    transaction.on_commit(lambda: _known.add(name))
    return name


def make_partitions(now: datetime | None = None, ahead_days: int = AHEAD_DAYS) -> list[str]:
    """Partitions from today to ``ahead_days`` ahead, for every partitioned table."""
    today = (now or datetime.now(UTC)).astimezone(UTC).date()
    made = []
    for spec in TABLES:
        for offset in range(0, ahead_days + 1):
            made.append(ensure(spec, today + timedelta(days=offset)))
    return sorted(set(made))


def partitions(spec: Partitioned) -> list[tuple[str, date]]:
    """``[(name, start)]`` of the attached partitions that follow the naming rule."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = %s",
            [spec.table],
        )
        names = [r[0] for r in cur.fetchall()]
    out = []
    for name in names:
        m = spec.pattern().match(name)
        if m:
            out.append((name, datetime.strptime(m.group(1), "%Y%m%d").date()))
    return sorted(out, key=lambda x: x[1])


def retention_days(spec: Partitioned) -> int:
    if spec is SIGNALS:
        return settings.INTEL_SIGNAL_RETENTION_DAYS
    return settings.INTEL_ENGAGEMENT_RETENTION_DAYS


def oldest_kept(spec: Partitioned, now: datetime | None = None) -> datetime:
    """Rows older than this are past retention."""
    return (now or datetime.now(UTC)) - timedelta(days=retention_days(spec))


def drop_expired(now: datetime | None = None) -> list[str]:
    """Drop every partition whose whole range is older than its table's retention."""
    dropped = []
    for spec in TABLES:
        cutoff = oldest_kept(spec, now)
        for name, start in partitions(spec):
            upper = datetime(start.year, start.month, start.day, tzinfo=UTC) + timedelta(
                days=spec.step_days
            )
            if upper <= cutoff:
                with transaction.atomic(), connection.cursor() as cur:
                    cur.execute(f"DROP TABLE IF EXISTS {name}")  # noqa: S608 - our own name
                _known.discard(name)
                dropped.append(name)
    return dropped


def purge_batches(now: datetime | None = None) -> int:
    """Batch dedupe rows live 48 h: a client retries a batch within minutes."""
    from ..models import SignalBatch

    cutoff = (now or datetime.now(UTC)) - BATCH_RETENTION
    deleted, _ = SignalBatch.objects.filter(received_at__lt=cutoff).delete()
    return deleted


def forget_known() -> None:
    """Test hook: partitions created in a rolled-back test transaction are gone."""
    _known.clear()
