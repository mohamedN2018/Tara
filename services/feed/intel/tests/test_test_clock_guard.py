"""WP 4b.15: ``X-Tara-Test-Now`` is honoured only with the flag on, in development, for a
registered seed or test account; feed (ranking ``now``) and feed-signals
(``received_at``) share it; production refuses the flag at check and readiness time."""

import json
import uuid
from datetime import UTC, datetime
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import RequestFactory
from django.utils import timezone

from intel import checks, clock, origin, readiness
from intel.models import SyntheticAccount

from .helpers import acct, batch, ev, signal_rows

pytestmark = pytest.mark.django_db
FAKE = "2026-12-24T10:30:00+00:00"
FAKE_AT = datetime(2026, 12, 24, 10, 30, tzinfo=UTC)


def _register(account, label="test-clock"):
    SyntheticAccount.objects.create(account_id=account, label=label)
    origin.clear_cache()


def _request(header=FAKE):
    meta = {"HTTP_X_TARA_TEST_NOW": header} if header is not None else {}
    return RequestFactory().get("/", **meta)


@pytest.fixture
def armed(settings):
    """Every gate open: flag on, development, a registered test account."""
    settings.INTEL_TEST_CLOCK_ENABLED = True
    settings.TARA_ENV = "development"
    me = acct()
    _register(me)
    return me


def _is_real(value):
    return abs((value - timezone.now()).total_seconds()) < 60


def test_all_gates_open_the_header_sets_now(armed):
    assert clock.request_now(_request(), armed) == FAKE_AT
    assert clock.request_now(_request("1798108200"), armed) == FAKE_AT
    # A naive time is UTC.
    assert clock.request_now(_request("2026-12-24T10:30:00"), armed) == FAKE_AT


def test_flag_off_changes_nothing(armed, settings):
    settings.INTEL_TEST_CLOCK_ENABLED = False
    assert _is_real(clock.request_now(_request(), armed))


@pytest.mark.parametrize("env", ["production", "staging", "test", ""])
def test_outside_development_changes_nothing(armed, settings, env):
    settings.TARA_ENV = env
    assert _is_real(clock.request_now(_request(), armed))


def test_unregistered_account_changes_nothing(armed):
    assert _is_real(clock.request_now(_request(), acct()))
    assert _is_real(clock.request_now(_request(), None))


def test_no_header_or_garbage_is_the_real_clock(armed):
    assert _is_real(clock.request_now(_request(None), armed))
    assert _is_real(clock.request_now(_request("not a time"), armed))


def test_seed_label_counts_as_registered(settings):
    settings.INTEL_TEST_CLOCK_ENABLED = True
    me = acct()
    _register(me, "seed-dataset")
    assert clock.request_now(_request(), me) == FAKE_AT


# ---- feed: the ranking now of a Home first page ---------------------------------------


def _home(client_for, me, header):
    from feed import ranking

    seen = {}
    real = ranking.first_page

    def spy(viewer, size, now, claims=None):
        seen["now"] = now
        return real(viewer, size, now, claims)

    extra = {"HTTP_X_TARA_TEST_NOW": header} if header else {}
    with mock.patch("feed.ranking.first_page", side_effect=spy):
        resp = client_for(me).get("/api/v1/feed/", {"mode": "for_you"}, **extra)
    assert resp.status_code == 200
    return seen["now"]


def test_feed_ranks_at_the_test_clock(client_for, armed):
    assert _home(client_for, armed, FAKE) == FAKE_AT


def test_feed_ignores_the_header_for_each_closed_gate(client_for, armed, settings):
    assert _is_real(_home(client_for, acct(), FAKE))  # not registered
    settings.TARA_ENV = "production"
    assert _is_real(_home(client_for, armed, FAKE))
    settings.TARA_ENV = "development"
    settings.INTEL_TEST_CLOCK_ENABLED = False
    assert _is_real(_home(client_for, armed, FAKE))


# ---- feed-signals: received_at -----------------------------------------------------


def _ingest(client_for, me, header, settings):
    settings.INTEL_ACCEPT_SYNTHETIC = True  # a registered account's rows are stored
    body = batch(ev("post_open", f"post:{uuid.uuid4()}"))
    extra = {"HTTP_X_TARA_TEST_NOW": header} if header else {}
    resp = client_for(me).post(
        "/api/v1/feed/signals/", data=json.dumps(body), content_type="application/json", **extra
    )
    assert resp.status_code == 202, resp.content
    assert resp.json()["data"]["accepted"] == 1
    (row,) = signal_rows(account_id=me)
    return row["received_at"]


def test_signals_record_the_test_clock(client_for, armed, settings):
    assert _ingest(client_for, armed, FAKE, settings) == FAKE_AT


def test_signals_ignore_the_header_with_the_flag_off(client_for, armed, settings):
    settings.INTEL_TEST_CLOCK_ENABLED = False
    assert _is_real(_ingest(client_for, armed, FAKE, settings))


def test_signals_ignore_the_header_outside_development(client_for, armed, settings):
    settings.TARA_ENV = "staging"
    assert _is_real(_ingest(client_for, armed, FAKE, settings))


# ---- production refuses the flag -----------------------------------------------------


def test_deploy_check_and_readiness_refuse_the_flag_outside_development(settings, client):
    settings.INTEL_TEST_CLOCK_ENABLED = True
    settings.TARA_ENV = "development"
    assert checks.clock_outside_dev() == []
    assert readiness.clock_check() == (True, "ok")
    settings.TARA_ENV = "production"
    assert [e.id for e in checks.clock_outside_dev()] == ["intel.E005"]
    assert readiness.clock_check()[0] is False
    with pytest.raises(SystemCheckError, match="intel.E005"):
        call_command("check", "--deploy")
    resp = client.get("/readyz/")
    assert resp.status_code == 503
    assert resp.json()["checks"]["intel_test_clock"] != "ok"


def test_flag_off_in_production_is_fine(settings):
    settings.TARA_ENV = "production"
    settings.INTEL_TEST_CLOCK_ENABLED = False
    assert checks.clock_outside_dev() == []
    assert readiness.clock_check() == (True, "ok")
