"""R3 WP A1/A2 (06 section 13): intel/0008, 0009 and 0010 run forward and backward on
an empty and a populated partition, are additive, and leave home@1, home@2 and the
home@2b drafts byte-unchanged."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from intel.models import RankingConfig

# Inside the test's transaction (PostgreSQL DDL is transactional): the round trip is
# rolled back afterwards, so later tests see the migrated database untouched.
pytestmark = pytest.mark.django_db

BEFORE = ("intel", "0007_impression_def")
COLUMNS = {"dwell_ms", "state", "consumed_dwell_only", "last_displayed_at", "visits"}
DRAFTS = ("home@2c", "home@2c-r15", "home@2c-r30")


def _latest():
    executor = MigrationExecutor(connection)
    return [key for key in executor.loader.graph.leaf_nodes() if key[0] == "intel"]


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(target)


def _columns(table):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s", [table]
        )
        return {r[0] for r in cur.fetchall()}


def _partitions():
    with connection.cursor() as cur:
        cur.execute(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
            " JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'intel_user_item_engagement'"
        )
        return [r[0] for r in cur.fetchall()]


def _rows():
    with connection.cursor() as cur:
        cur.execute("SELECT account_id, item_id FROM intel_user_item_engagement ORDER BY 1")
        return cur.fetchall()


def _table_exists(name):
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", [name])
        return cur.fetchone()[0] is not None


def _released():
    return {
        (r.version, r.note): r.params
        for r in RankingConfig.objects.filter(surface="home").exclude(note__in=DRAFTS)
    }


def test_forward_and_backward_on_an_empty_and_a_populated_partition():
    parts = _partitions()
    assert len(parts) >= 2
    released = _released()
    account, item = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO intel_user_item_engagement (account_id, item_id, item_type, first_at,"
            " last_at, data_origin, dwell_ms, state, visits) VALUES (%s, %s, 'post', %s, %s,"
            " 'test', 9000, 3, 2)",
            [account, item, now, now],
        )
    populated = _rows()
    assert (uuid.UUID(account), uuid.UUID(item)) in [tuple(r) for r in populated]

    _migrate([BEFORE])
    for table in ["intel_user_item_engagement", *parts]:
        assert not COLUMNS & _columns(table), table
    assert not _table_exists("intel_feed_session")
    assert not RankingConfig.objects.filter(note__in=DRAFTS).exists()
    assert _rows() == populated  # the rows survive the backward step

    _migrate(_latest())
    for table in ["intel_user_item_engagement", *parts]:  # empty and populated alike
        assert COLUMNS <= _columns(table), table
    with connection.cursor() as cur:
        cur.execute(
            "SELECT dwell_ms, state, consumed_dwell_only, last_displayed_at, visits"
            " FROM intel_user_item_engagement WHERE account_id = %s",
            [account],
        )
        assert cur.fetchone() == (0, None, False, None, 0)  # defaults on the old row
    assert _table_exists("intel_feed_session")
    assert sorted(RankingConfig.objects.filter(note__in=DRAFTS).values_list("note", flat=True)) == (
        sorted(DRAFTS)
    )
    assert _released() == released  # home@1, home@2, home@2b byte-unchanged


def test_the_drafts_are_idempotent_never_active_and_schema_4():
    import importlib

    from django.apps import apps

    module = importlib.import_module("intel.migrations.0010_home_v2c_drafts")
    before = RankingConfig.objects.filter(note__in=DRAFTS).count()
    module.load(apps, None)
    assert RankingConfig.objects.filter(note__in=DRAFTS).count() == before == 3
    rows = RankingConfig.objects.filter(note__in=DRAFTS)
    assert {r.status for r in rows} == {"draft"}
    assert {r.schema_version for r in rows} == {4}
    shares = {r.note: r.params["mix"]["recommended"] for r in rows}
    assert shares == {"home@2c": 0.0, "home@2c-r15": 0.15, "home@2c-r30": 0.30}
    active = RankingConfig.objects.get(surface="home", status="active")
    assert active.note not in DRAFTS
