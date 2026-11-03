"""Roadmap 1.0b: the ads serving switch and its production deploy check."""

import os
import subprocess
import sys
import time
from io import StringIO

import jwt
import pytest
from config.settings import ads_serving_enabled
from django.core.checks import ERROR, WARNING
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.urls import reverse
from rest_framework.test import APIClient

from ads import checks, serve_tokens, services
from ads.tests.test_ads import _acct, _make_active_creative

STRONG_SECRET = "9f" * 32


def _internal_client(settings) -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "feed", "aud": "ads-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _slot(settings):
    return _internal_client(settings).get(reverse("ads-feed-slot"), {"viewer": _acct()})


# ---- the setting ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, True),
        ({"TARA_ENV": "development"}, True),
        ({"TARA_ENV": "staging"}, True),
        ({"TARA_ENV": "production"}, False),
        ({"TARA_ENV": " Production "}, False),
        # Compose passes unset variables through as empty strings.
        ({"TARA_ENV": "production", "ADS_SERVING_ENABLED": ""}, False),
        ({"TARA_ENV": "production", "ADS_SERVING_ENABLED": "true"}, True),
        ({"TARA_ENV": "development", "ADS_SERVING_ENABLED": "false"}, False),
        ({"TARA_ENV": "development", "ADS_SERVING_ENABLED": "0"}, False),
        # Anything unrecognised is off: fail closed.
        ({"TARA_ENV": "development", "ADS_SERVING_ENABLED": "maybe"}, False),
    ],
)
def test_serving_defaults_by_tara_env_and_an_explicit_value_wins(environ, expected):
    assert ads_serving_enabled(environ) is expected


def _loaded_setting(**env: str) -> str:
    environ = {k: v for k, v in os.environ.items() if k not in ("TARA_ENV", "ADS_SERVING_ENABLED")}
    environ.update(env)
    out = subprocess.run(  # noqa: S603 - fixed argv, the test's own interpreter
        [sys.executable, "-c", "import config.settings as s; print(s.ADS_SERVING_ENABLED)"],
        env=environ,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_settings_module_reads_the_switch_from_the_environment():
    assert _loaded_setting(TARA_ENV="production") == "False"
    assert _loaded_setting(TARA_ENV="production", ADS_SERVING_ENABLED="true") == "True"
    assert _loaded_setting(TARA_ENV="development") == "True"


# ---- the feed slot --------------------------------------------------------------


@pytest.mark.django_db
def test_feed_slot_is_empty_and_mints_no_token_when_serving_is_off(settings, monkeypatch):
    _make_active_creative(_acct())
    settings.ADS_SERVING_ENABLED = False

    def _no_mint(*args, **kwargs):
        raise AssertionError("minted a serve token while serving is off")

    monkeypatch.setattr(serve_tokens, "issue", _no_mint)
    resp = _slot(settings)
    assert resp.status_code == 200
    assert resp.json() == {"data": {"sponsored": None}}
    assert services.pick_for_viewer(_acct(), "feed") is None


@pytest.mark.django_db
def test_feed_slot_still_requires_internal_auth_when_serving_is_off(settings):
    _make_active_creative(_acct())
    settings.ADS_SERVING_ENABLED = False
    assert APIClient().get(reverse("ads-feed-slot"), {"viewer": _acct()}).status_code == 401


@pytest.mark.django_db
def test_switching_serving_back_on_serves_the_same_campaign(settings):
    _make_active_creative(_acct())
    settings.ADS_SERVING_ENABLED = False
    assert _slot(settings).json()["data"]["sponsored"] is None
    settings.ADS_SERVING_ENABLED = True
    sponsored = _slot(settings).json()["data"]["sponsored"]
    assert sponsored["sponsored"] is True and sponsored["token"]


@pytest.mark.django_db
def test_advertisers_can_still_build_campaigns_while_serving_is_off(client_for, settings):
    settings.ADS_SERVING_ENABLED = False
    owner = _acct()
    resp = client_for(owner).post(
        reverse("ads:campaigns"), {"name": "Draft", "budget": "10.00"}, format="json"
    )
    assert resp.status_code == 201


# ---- the deploy check -------------------------------------------------------------


@pytest.mark.parametrize("enabled", [True, False])
def test_serving_check_is_silent_outside_production(settings, enabled):
    settings.TARA_ENV = "development"
    settings.ADS_SERVING_ENABLED = enabled
    assert checks.check_serving_switch() == []


def test_serving_on_in_production_without_payment_verification_is_an_error(settings):
    settings.TARA_ENV = "production"
    settings.ADS_SERVING_ENABLED = True
    [message] = checks.check_serving_switch()
    assert (message.id, message.level) == ("ads.E001", ERROR)


def test_serving_off_in_production_is_only_a_warning(settings):
    settings.TARA_ENV = "production"
    settings.ADS_SERVING_ENABLED = False
    [message] = checks.check_serving_switch()
    assert (message.id, message.level) == ("ads.W001", WARNING)


def test_payment_verification_lifts_the_serving_check(settings, monkeypatch):
    monkeypatch.setattr(checks, "PAYMENT_VERIFICATION_AVAILABLE", True)
    settings.TARA_ENV = "production"
    settings.ADS_SERVING_ENABLED = True
    assert checks.check_serving_switch() == []


def _deploy_gate() -> None:
    call_command("check", deploy=True, fail_level="ERROR", stdout=StringIO(), stderr=StringIO())


def test_production_deploy_gate_passes_with_serving_off_and_fails_with_it_on(settings):
    settings.TARA_ENV = "production"
    # DEBUG keeps the shared tara.E00x secret checks (dev values in tests) out of this test.
    settings.DEBUG = True
    settings.ADS_SERVE_TOKEN_SECRET = STRONG_SECRET
    settings.ADS_SERVING_ENABLED = False
    _deploy_gate()

    settings.ADS_SERVING_ENABLED = True
    with pytest.raises(SystemCheckError, match=r"ads\.E001"):
        _deploy_gate()
