"""The opt-in search signal (Tara Intelligence WP 8.7-B2, owner decision 7).

Off (the default, or no row): a search emits nothing. On: one ``search.queried``
per first-page search, carrying sha256 term keys only, never the query text."""

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.test import TestCase
from django.urls import reverse

from searchsvc import handlers
from searchsvc.models import OutboxEvent, SearchSignalOptIn
from tara_common.signal_terms import term_keys
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")
QUERY = "Cooking وصفات   pasta"


def acct() -> str:
    return str(uuid.uuid4())


def changed(account_id: str, enabled: bool, at: datetime) -> None:
    payload = {"account_id": account_id, "enabled": enabled, "at": at.isoformat()}
    if SCHEMAS.exists():
        import jsonschema

        schema = json.loads((SCHEMAS / "intel.search_signal.changed.v1.json").read_text())
        jsonschema.validate(payload, schema, format_checker=jsonschema.FormatChecker())
    # The cache is written on commit, as the consumer's transaction would.
    with TestCase.captureOnCommitCallbacks(execute=True):
        handlers.on_search_signal_changed(
            EventEnvelope(
                event_type="intel.search_signal.changed",
                subject_id=account_id,
                producer="feed-service",
                payload=payload,
            )
        )


def _search(client, q=QUERY, **params):
    resp = client.get(reverse("searchsvc:search"), {"q": q, **params})
    assert resp.status_code == 200, resp.content
    return resp


def _events():
    return list(OutboxEvent.objects.filter(event_type="search.queried").order_by("created_at"))


def test_off_by_default_emits_nothing(client_for):
    me = acct()
    _search(client_for(me))
    assert _events() == []
    assert not SearchSignalOptIn.objects.exists()


def test_turned_off_emits_nothing(client_for):
    me = acct()
    changed(me, True, T0)
    changed(me, False, T0 + timedelta(minutes=1))
    _search(client_for(me))
    assert _events() == []


def test_on_emits_one_event_with_hashes_only(client_for):
    me = acct()
    changed(me, True, T0)
    _search(client_for(me))
    rows = _events()
    assert len(rows) == 1
    payload = rows[0].payload["payload"]
    assert set(payload) == {"account_id", "term_keys", "queried_at"}
    assert payload["account_id"] == me
    assert payload["term_keys"] == term_keys(QUERY)
    assert payload["term_keys"] and all(
        re.fullmatch(r"[0-9a-f]{64}", k) for k in payload["term_keys"]
    )
    text = json.dumps(rows[0].payload, ensure_ascii=False).lower()
    for word in ("cooking", "pasta", "وصفات", "query", '"q"', "text"):
        assert word not in text
    if SCHEMAS.exists():
        import jsonschema

        schema = json.loads((SCHEMAS / "search.queried.v1.json").read_text())
        jsonschema.validate(payload, schema, format_checker=jsonschema.FormatChecker())


def test_later_pages_empty_queries_and_other_accounts_emit_nothing(client_for):
    me, other = acct(), acct()
    changed(me, True, T0)
    first = _search(client_for(me), sort="recent").json()
    cursor = first["page"]["next_cursor"]
    if cursor:
        _search(client_for(me), sort="recent", cursor=cursor)
    _search(client_for(me), q="")
    _search(client_for(me), q="a")  # no token of 2+ characters
    _search(client_for(other))  # never opted in
    assert len(_events()) == 1


def test_flag_off_emits_nothing(client_for, settings):
    settings.SEARCH_EMIT_QUERY_SIGNALS = False
    me = acct()
    changed(me, True, T0)
    _search(client_for(me))
    assert _events() == []


def test_newest_state_wins():
    me = acct()
    changed(me, True, T0 + timedelta(minutes=5))
    changed(me, False, T0)  # older, late
    assert SearchSignalOptIn.objects.get(account_id=me).enabled is True
    changed(me, False, T0 + timedelta(minutes=6))
    assert SearchSignalOptIn.objects.get(account_id=me).enabled is False


def test_search_reads_the_cache_only_and_the_beat_rewarms_it(client_for, django_assert_num_queries):
    from django.core.cache import cache

    from searchsvc import signals, tasks

    me = acct()
    changed(me, True, T0)
    assert signals.enabled_for(me) is True
    cache.clear()  # e.g. a Redis restart
    assert signals.enabled_for(me) is False  # unknown reads as off
    with django_assert_num_queries(0):
        signals.enabled_for(me)
    assert tasks.warm_signal_optins() == 1
    _search(client_for(me))
    assert len(_events()) == 1
