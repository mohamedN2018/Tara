"""WP 4c.9-B3 (08 section 7.12): the impression rule a ``feed_impression`` was measured
with is stored on its row (``impression_def``), so rates of rule 1 and rule 2 never
mix. Range from the config (``delivery.impression.def_version``), never a literal."""

import json
import uuid

import pytest
from django.db import connection

from intel import config
from intel.config import store
from intel.signals import partitions

from .helpers import acct, batch, ev, signal_rows

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/signals/"


def _send(client_for, account, *events):
    resp = client_for(account).post(
        URL, data=json.dumps(batch(*events)), content_type="application/json"
    )
    assert resp.status_code == 202, resp.content
    return resp.json()["data"]


def _item():
    return f"post:{uuid.uuid4()}"


def _top() -> int:
    return config.for_surface("home").get("delivery.impression.def_version")


def test_the_rule_sent_is_stored_and_a_legacy_client_is_rule_1(client_for):
    me = acct()
    assert _top() == 2  # the defaults ship rule 2
    out = _send(
        client_for,
        me,
        ev("feed_impression", _item(), idef=2),
        ev("feed_impression", _item(), idef=1),
        ev("feed_impression", _item()),  # a client from before rule 2
    )
    assert out == {"accepted": 3, "duplicate": False, "rejected": {}}
    stored = sorted(r["impression_def"] for r in signal_rows(account_id=me))
    assert stored == [1, 1, 2]


def test_out_of_range_drops_the_event_not_the_batch(client_for):
    me = acct()
    out = _send(
        client_for,
        me,
        ev("feed_impression", _item(), idef=_top() + 1),
        ev("feed_impression", _item(), idef=0),
        ev("feed_impression", _item(), idef="two"),
        ev("feed_impression", _item(), idef=2),
    )
    assert out["accepted"] == 1
    assert out["rejected"] == {"invalid_idef": 2, "invalid": 1}
    assert [r["impression_def"] for r in signal_rows(account_id=me)] == [2]


def test_the_range_follows_the_config_not_a_literal(client_for, monkeypatch):
    """With ``def_version`` 1 in the active config, ``idef`` 2 is out of range."""
    version, params = store.resolve("home")
    lowered = json.loads(json.dumps(params))
    lowered["delivery"]["impression"]["def_version"] = 1
    monkeypatch.setattr(store, "resolve", lambda surface: (version, lowered))
    me = acct()
    out = _send(
        client_for, me, ev("feed_impression", _item(), idef=2), ev("feed_impression", _item())
    )
    assert out["accepted"] == 1 and out["rejected"] == {"invalid_idef": 1}
    assert [r["impression_def"] for r in signal_rows(account_id=me)] == [1]


def test_idef_on_another_event_type_is_an_unknown_field(client_for):
    me, item = acct(), _item()
    out = _send(
        client_for,
        me,
        ev("post_open", item, idef=1),
        ev("video_start", item, play_index=1, idef=2),
        ev("post_open", item),
    )
    assert out["accepted"] == 1
    assert out["rejected"] == {"unknown_field": 2}
    (row,) = signal_rows(account_id=me)
    assert row["event_type"] == "post_open" and row["impression_def"] is None


def test_other_events_are_accepted_as_before_and_carry_no_rule(client_for):
    me, item = acct(), _item()
    out = _send(
        client_for,
        me,
        ev("post_open", item),
        ev("video_start", item, play_index=1),
        ev("video_progress", item, play_index=1, watch_ms=500, pos_ms=500),
        ev("profile_visit", f"profile:{uuid.uuid4()}"),
    )
    assert out == {"accepted": 4, "duplicate": False, "rejected": {}}
    assert {r["impression_def"] for r in signal_rows(account_id=me)} == {None}


def test_server_rows_never_set_it():
    from intel.models import EventType, ItemType
    from intel.signals.server import record

    me = acct()
    assert record(me, EventType.POST_HIDE, ItemType.POST, uuid.uuid4(), uuid.uuid4())
    rows = signal_rows(account_id=me)
    assert rows and {r["source"] for r in rows} == {"server"}
    assert {r["impression_def"] for r in rows} == {None}


def test_the_column_is_on_the_parent_and_on_every_partition():
    from django.utils import timezone

    partitions.ensure(partitions.SIGNALS, timezone.now().date())
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname, a.atttypid::regtype::text, a.attnotnull
            FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
            WHERE a.attname = 'impression_def' AND NOT a.attisdropped
              AND (c.relname = 'intel_signal_event'
                   OR c.oid IN (SELECT inhrelid FROM pg_inherits
                                WHERE inhparent = 'intel_signal_event'::regclass))
            """
        )
        found = {name: (kind, notnull) for name, kind, notnull in cur.fetchall()}
        cur.execute(
            "SELECT count(*) FROM pg_inherits WHERE inhparent = 'intel_signal_event'::regclass"
        )
        (n_partitions,) = cur.fetchone()
    assert found.pop("intel_signal_event") == ("smallint", False)
    assert n_partitions >= 1 and len(found) == n_partitions
    assert set(found.values()) == {("smallint", False)}
