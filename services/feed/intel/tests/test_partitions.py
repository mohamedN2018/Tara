"""WP 2.2: partitions exist 7 days ahead, old ones are dropped, batch rows purged."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from intel.models import SignalBatch
from intel.signals import partitions

pytestmark = pytest.mark.django_db


def _names(spec):
    return {name for name, _ in partitions.partitions(spec)}


def test_partitions_seven_days_ahead():
    now = datetime.now(UTC)
    partitions.make_partitions(now)
    names = _names(partitions.SIGNALS)
    for offset in range(0, 8):
        day = (now + timedelta(days=offset)).date()
        assert f"intel_signal_event_p{day:%Y%m%d}" in names
    weeks = _names(partitions.ENGAGEMENT)
    for offset in (0, 7):
        day = (now + timedelta(days=offset)).date()
        monday = day - timedelta(days=day.weekday())
        assert f"intel_user_item_engagement_p{monday:%Y%m%d}" in weeks


def test_make_partitions_is_idempotent():
    first = partitions.make_partitions()
    partitions.forget_known()  # as a fresh process would
    second = partitions.make_partitions()
    assert first == second


def test_drop_past_retention(settings):
    settings.INTEL_SIGNAL_RETENTION_DAYS = 30
    settings.INTEL_ENGAGEMENT_RETENTION_DAYS = 30
    now = datetime.now(UTC)
    old = (now - timedelta(days=40)).date()
    kept = (now - timedelta(days=29)).date()
    old_name = partitions.ensure(partitions.SIGNALS, old)
    kept_name = partitions.ensure(partitions.SIGNALS, kept)
    old_week = partitions.ensure(partitions.ENGAGEMENT, (now - timedelta(days=60)).date())

    dropped = partitions.drop_expired(now)

    assert old_name in dropped and old_week in dropped
    assert kept_name not in dropped
    names = _names(partitions.SIGNALS)
    assert old_name not in names and kept_name in names
    # Idempotent: nothing left to drop.
    assert partitions.drop_expired(now) == []


def test_dev_retention_keeps_older_partitions(settings):
    settings.INTEL_SIGNAL_RETENTION_DAYS = 90
    now = datetime.now(UTC)
    name = partitions.ensure(partitions.SIGNALS, (now - timedelta(days=60)).date())
    assert name not in partitions.drop_expired(now)


def test_partition_boundaries_are_utc_days():
    day = datetime(2026, 1, 15, tzinfo=UTC).date()
    name = partitions.ensure(partitions.SIGNALS, day)
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            "SELECT pg_get_expr(c.relpartbound, c.oid) FROM pg_class c WHERE c.relname = %s",
            [name],
        )
        bound = cur.fetchone()[0]
    assert "2026-01-15 00:00:00+00" in bound and "2026-01-16 00:00:00+00" in bound


def test_purge_signal_batches_after_48h():
    now = datetime.now(UTC)
    old = SignalBatch.objects.create(
        account_id=uuid.uuid4(), batch_id=uuid.uuid4(), received_at=now - timedelta(hours=49)
    )
    fresh = SignalBatch.objects.create(
        account_id=uuid.uuid4(), batch_id=uuid.uuid4(), received_at=now - timedelta(hours=47)
    )
    assert partitions.purge_batches(now) == 1
    remaining = set(SignalBatch.objects.values_list("batch_id", flat=True))
    assert remaining == {fresh.batch_id}
    assert old.batch_id not in remaining


def test_task_and_command_run(capsys):
    from django.core.management import call_command

    from intel import tasks

    result = tasks.maintain_partitions()
    assert result["ensured"] >= 9
    call_command("intel_make_partitions")
    assert "ensured" in capsys.readouterr().out
