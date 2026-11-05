"""Writes into ``intel_signal_event`` (partitioned; the model is read-only).

Client batches are written with one ``COPY``; a bus or server row with one
``INSERT``. Both run inside the caller's transaction, so a server action and its
signal row commit or roll back together. The partition for the row's
``received_at`` day is created first if it is missing.
"""

from __future__ import annotations

from dataclasses import astuple, dataclass, fields
from datetime import UTC, datetime

from django.db import connection

from tara_events.envelope import uuid7

from . import partitions


@dataclass
class SignalRow:
    account_id: object
    event_type: str
    item_type: str
    item_id: object
    source: str
    data_origin: str
    occurred_at: datetime
    received_at: datetime
    id: object = None
    client_event_id: object = None
    batch_id: object = None
    session_id: object = None
    author_id: object = None
    surface: str | None = None
    position: int | None = None
    watch_ms: int | None = None
    pos_ms: int | None = None
    duration_ms: int | None = None
    play_index: int | None = None
    rank_source: str | None = None
    attributed: bool = False
    cfg_version: str | None = None
    variant: str | None = None
    pred: bytes | None = None
    flags: int = 0

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = uuid7()


COLUMNS = tuple(f.name for f in fields(SignalRow))
_COLUMN_SQL = ", ".join(COLUMNS)


def _ensure_partitions(rows: list[SignalRow]) -> None:
    for day in {r.received_at.astimezone(UTC).date() for r in rows}:
        partitions.ensure(partitions.SIGNALS, day)


def copy_rows(rows: list[SignalRow]) -> int:
    """Write ``rows`` with one ``COPY`` (client batches, the synthetic command)."""
    if not rows:
        return 0
    _ensure_partitions(rows)
    with connection.cursor() as cur:
        with cur.copy(f"COPY intel_signal_event ({_COLUMN_SQL}) FROM STDIN") as copy:  # noqa: S608
            for row in rows:
                copy.write_row(astuple(row))
    return len(rows)


def insert_row(row: SignalRow) -> None:
    """One bus or server row, in the caller's transaction."""
    _ensure_partitions([row])
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    with connection.cursor() as cur:
        cur.execute(
            f"INSERT INTO intel_signal_event ({_COLUMN_SQL}) VALUES ({placeholders})",  # noqa: S608
            list(astuple(row)),
        )
