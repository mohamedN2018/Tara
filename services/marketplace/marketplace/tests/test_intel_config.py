"""The local ``marketplace`` config (Tara Intelligence WP 5.5): handler and cache
only. Marketplace has no ranked surface yet, so no view reads it and nothing is
exposed today (R4 deviation, results/r4-track-b.md)."""

from datetime import UTC, datetime, timedelta

import pytest

from marketplace import intel_config
from marketplace.handlers import on_intel_config_published
from marketplace.models import IntelConfig, OutboxEvent
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def publish(version, params, at, experiment=None, surface="marketplace"):
    on_intel_config_published(
        EventEnvelope(
            event_type="intel.config.published",
            subject_id=surface,
            producer="feed-service",
            payload={
                "surface": surface,
                "version": version,
                "params": params,
                "published_at": at.isoformat(),
                "experiment": experiment,
            },
        )
    )


def test_handler_keeps_the_newest_and_ignores_older_or_equal():
    publish(2, {"rank": {"w": 1}}, T0)
    publish(1, {"rank": {"w": 0}}, T0 - timedelta(hours=1))
    publish(2, {"rank": {"w": 3}}, T0)
    publish(4, {}, T0 + timedelta(hours=1), surface="discovery")  # not marketplace's
    row = IntelConfig.objects.get()
    assert (row.surface, row.version, row.params) == ("marketplace", 2, {"rank": {"w": 1}})
    publish(3, {"rank": {"w": 2}}, T0 + timedelta(minutes=1))
    assert IntelConfig.objects.get().version == 3


def test_parity_no_row_and_nothing_exposed_without_an_experiment():
    assert intel_config.served("6f03e73e-ca0f-4bec-a65d-9c4aad56871b").params == {}
    publish(3, {"rank": {"w": 2}}, T0)
    served = intel_config.served("6f03e73e-ca0f-4bec-a65d-9c4aad56871b")
    assert (served.params, served.variant) == ({}, None)  # no marketplace params read yet
    assert not OutboxEvent.objects.filter(event_type="intel.experiment.exposed").exists()
