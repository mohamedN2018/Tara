"""Shared helpers for the intel tests."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.db import connection
from django.utils import timezone

from tara_events.consumer import idempotent
from tara_events.dispatch import handlers_for
from tara_events.envelope import EventEnvelope


def acct() -> str:
    return str(uuid.uuid4())


def event(event_type: str, payload: dict, *, actor=None, at=None) -> EventEnvelope:
    kwargs = {"occurred_at": at.isoformat()} if at is not None else {}
    return EventEnvelope(
        event_type=event_type,
        subject_id=str(uuid.uuid4()),
        producer="test",
        payload=payload,
        actor_id=actor,
        **kwargs,
    )


def deliver(env: EventEnvelope, times: int = 1, *, only_intel: bool = False) -> None:
    """Dispatch like the worker does, once per handler and event id. ``only_intel``
    skips feed's own handlers (some call Graph)."""
    from feed.models import ProcessedEvent

    for _ in range(times):
        for fn in handlers_for(env.event_type):
            if only_intel and not fn.__name__.startswith("intel_"):
                continue
            with idempotent(ProcessedEvent, env.event_id, f"feed:{fn.__name__}") as fresh:
                if fresh:
                    fn(env)


def signal_rows(**where) -> list[dict]:
    clauses, params = [], []
    for key, value in where.items():
        clauses.append(f"{key} = %s")
        params.append(value)
    sql = "SELECT * FROM intel_signal_event"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY received_at, id"
    with connection.cursor() as cur:
        cur.execute(sql, params)  # noqa: S608 - test helper, fixed column names
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def ev(t: str, item: str, *, ts=None, **extra) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "t": t,
        "item": item,
        "ts": (ts or timezone.now()).isoformat(),
        **extra,
    }


def batch(*events, session=None, batch_id=None) -> dict:
    return {
        "batch_id": batch_id or str(uuid.uuid4()),
        "session_id": session or str(uuid.uuid4()),
        "events": list(events),
    }


def ago(**kw):
    return timezone.now() - timedelta(**kw)
