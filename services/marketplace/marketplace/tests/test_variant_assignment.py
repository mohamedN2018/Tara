"""Marketplace buckets with ``tara_common.bucketing.assign_variant``, as feed does,
so when a ranked marketplace surface serves an experiment an account gets the same
variant everywhere (Tara Intelligence WP 5.5)."""

from datetime import UTC, datetime

import pytest

from marketplace import intel_config
from marketplace.models import IntelExposureSeen, OutboxEvent
from tara_common.bucketing import assign_variant

from .test_intel_config import publish

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
EXPERIMENT = {
    "key": "market_rank",
    "salt": "m1",
    "variants": [
        {"name": "a", "pct": 30, "version": 1, "params": {}},
        {"name": "b", "pct": 30, "version": 2, "params": {}},
    ],
}
# Expected names computed with tara_common.bucketing on 2026-11-06 (60% allocated).
FIXTURES = {
    "6f03e73e-ca0f-4bec-a65d-9c4aad56871b": "b",
    "0a4d6342-9255-4ac8-a7bd-58cfe6fe33f8": "b",
    "a7df4ed5-aecf-46ad-ac53-965f02945712": None,
    "d90b9d67-b10c-455d-ac6d-ff36f3166cb1": "a",
    "11111111-1111-4111-8111-111111111111": "a",
    "22222222-2222-4222-8222-222222222222": "a",
}


def test_same_variant_as_assign_variant_and_one_exposure_each():
    publish(5, {}, T0, experiment=EXPERIMENT)
    for account_id, expected in FIXTURES.items():
        assert assign_variant(account_id, EXPERIMENT) == expected
        for _ in range(2):
            assert intel_config.served(account_id).variant == expected
    exposed = OutboxEvent.objects.filter(event_type="intel.experiment.exposed")
    assert exposed.count() == 5  # once per allocated account, never twice
    assert IntelExposureSeen.objects.count() == 5
    assert {r.payload["payload"]["surface"] for r in exposed} == {"marketplace"}
