"""R3 WP A6 (07 WP 4b.8, 06 section 6.3): per-account first-page and peek throttles.

The rates are the active Home config's ``session.rate.*`` (30 and 60 a minute), not
settings: the 31st first page in a minute gets 429 with ``Retry-After``; later pages
(a cursor) are never throttled; another account is not affected; the window passes."""

from __future__ import annotations

import pytest
from django.core.cache import cache

from intel import config
from intel.tests import world as w

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)
    cache.clear()  # the throttle history lives in the default cache
    yield
    cache.clear()


class FrozenTimer:
    def __init__(self, monkeypatch):
        self.t = 1_800_000_000.0
        monkeypatch.setattr("rest_framework.throttling.SimpleRateThrottle.timer", lambda _: self.t)


def _viewer(n=25):
    viewer, friend = w.uid(), w.uid()
    for _ in range(n):
        w.feed_row(viewer, w.post(friend), friend)
    return viewer


def test_the_31st_first_page_in_a_minute_gets_429(client_for, monkeypatch):
    timer = FrozenTimer(monkeypatch)
    rate = config.for_surface("home").get("session.rate.first_page_per_min")
    assert rate == 30
    viewer = _viewer()
    client = client_for(viewer)
    cursor = None
    for i in range(rate):
        resp = client.get("/api/v1/feed/", {"mode": "for_you" if i % 2 else "recent"})
        assert resp.status_code == 200, i
        if i % 2:
            cursor = cursor or resp.json()["page"]["next_cursor"]
        timer.t += 1
    resp = client.get("/api/v1/feed/", {"mode": "for_you"})
    assert resp.status_code == 429
    assert 0 < int(resp["Retry-After"]) <= 60
    # Scrolling is not a refresh: a later page still works.
    assert client.get("/api/v1/feed/", {"mode": "for_you", "cursor": cursor}).status_code == 200
    # Another account has its own budget.
    assert client_for(_viewer(2)).get("/api/v1/feed/").status_code == 200
    timer.t += 61
    assert client.get("/api/v1/feed/").status_code == 200


def test_peeks_have_their_own_rate(client_for, monkeypatch):
    timer = FrozenTimer(monkeypatch)
    rate = config.for_surface("home").get("session.rate.peek_per_min")
    assert rate == 60
    client = client_for(_viewer(2))
    for _ in range(rate):
        assert client.get("/api/v1/feed/", {"peek": "1"}).status_code == 200
        timer.t += 0.5
    assert client.get("/api/v1/feed/", {"peek": "1"}).status_code == 429
    assert client.get("/api/v1/feed/").status_code == 200  # first pages unaffected


def test_the_rate_follows_the_active_config(client_for, monkeypatch):
    FrozenTimer(monkeypatch)
    real = config.for_surface

    def lower(surface, overrides=None):
        cfg = real(surface, overrides)
        if surface == "home":
            rate = {"first_page_per_min": 2, "peek_per_min": 60}
            params = {**cfg.params, "session": {**cfg.params["session"], "rate": rate}}
            return config.SurfaceConfig(cfg.surface, cfg.version, params)
        return cfg

    monkeypatch.setattr("feed.throttles.config.for_surface", lower)
    client = client_for(_viewer(2))
    assert [client.get("/api/v1/feed/").status_code for _ in range(3)] == [200, 200, 429]
