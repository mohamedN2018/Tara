"""WP 5.4 (02 section 10.2): exposure is written at assignment, at the account's
first serve of the surface under a running experiment, with or without telemetry;
once per (experiment, account). Other services report theirs with
``intel.experiment.exposed.v1``; feed's consumer writes the same row, idempotently."""

import pytest
from django.core.cache import cache

from intel import experiments
from intel.models import ExperimentExposure

from . import r4, variants  # noqa: F401 - r4 registers the bus handlers
from . import world as w
from .helpers import ADULT_CLAIMS, client_with_claims, deliver, event

pytestmark = pytest.mark.django_db


def _start():
    arms = [
        {"name": "control", "pct": 50, "version": variants.version("home@2b")},
        {"name": "r15", "pct": 50, "version": variants.version("home@2b-r15")},
    ]
    experiments.create("home.exp", "home", arms, salt="s1")
    experiments.start("home.exp", reason="test")
    experiments.clear_cache()


def test_first_for_you_page_writes_one_exposure_without_any_telemetry(redis_hot, monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    _start()
    viewer, friend = w.uid(), w.uid()
    w.feed_row(viewer, w.post(friend), friend)
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    cache.clear()
    for _ in range(3):
        assert client.get("/api/v1/feed/", {"mode": "for_you", "entry": "pull"}).status_code == 200
    rows = list(ExperimentExposure.objects.filter(account_id=viewer))
    assert len(rows) == 1
    assigned = experiments.assign(viewer, "home")
    assert rows[0].variant == assigned.variant and rows[0].surface == "home"
    # Telemetry was never sent: no intel_signal_event row is needed for the exposure.
    from .helpers import signal_rows

    assert signal_rows(account_id=viewer) == []


def test_chronological_modes_are_not_exposures(redis_hot, monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    _start()
    viewer = w.uid()
    client_with_claims(viewer, **ADULT_CLAIMS).get("/api/v1/feed/", {"mode": "recent"})
    assert not ExperimentExposure.objects.filter(account_id=viewer).exists()


def test_bus_exposure_is_idempotent():
    account = w.uid()
    payload = {
        "experiment_key": "discovery.people",
        "account_id": account,
        "variant": "b",
        "surface": "discovery",
        "exposed_at": "2026-11-06T10:00:00+00:00",
    }
    env = event("intel.experiment.exposed", payload)
    deliver(env, times=2, only_intel=True)
    deliver(event("intel.experiment.exposed", payload), only_intel=True)  # a new event id
    rows = list(ExperimentExposure.objects.filter(account_id=account))
    assert len(rows) == 1 and rows[0].variant == "b" and rows[0].surface == "discovery"
