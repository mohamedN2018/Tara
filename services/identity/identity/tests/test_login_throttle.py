"""Per-target login throttling (alongside the per-IP throttle and the lockout)."""

from __future__ import annotations

import copy

import pytest
from django.urls import reverse
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import SimpleRateThrottle

from identity.throttling import LoginTargetThrottle, email_ident

pytestmark = pytest.mark.django_db


@pytest.fixture
def rates(settings, monkeypatch):
    """Set throttle rates. DRF binds THROTTLE_RATES at import, so patch it too."""

    def apply(**overrides):
        rest = copy.deepcopy(settings.REST_FRAMEWORK)
        rest["DEFAULT_THROTTLE_RATES"].update(overrides)
        settings.REST_FRAMEWORK = rest
        monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", rest["DEFAULT_THROTTLE_RATES"])

    return apply


def _attempt(client, email, password, ip):
    return client.post(
        reverse("identity:login"),
        {"email": email, "password": password},
        format="json",
        REMOTE_ADDR=ip,
        HTTP_X_FORWARDED_FOR=ip,
    )


def test_target_throttle_stops_attempts_from_many_ips(api_client, rates, active_account):
    rates(auth_login="1000/min", auth_login_target="3/min")
    for n in range(3):
        resp = _attempt(api_client, active_account.email, "WrongPassw0rd!", f"10.0.0.{n}")
        assert resp.status_code == 401
    # A fresh IP does not get a fresh budget against the same account...
    blocked = _attempt(api_client, active_account.email, "DevPassw0rd!", "10.9.9.9")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "throttled"
    assert "Retry-After" in blocked.headers


def test_target_throttle_is_per_email(api_client, rates, active_account):
    rates(auth_login="1000/min", auth_login_target="2/min")
    for _ in range(2):
        _attempt(api_client, "someone.else@tara.local", "WrongPassw0rd!", "10.0.0.1")
    # ...but other accounts are unaffected.
    assert _attempt(api_client, active_account.email, "DevPassw0rd!", "10.0.0.1").status_code == 200


def test_target_throttle_normalises_the_email(api_client, rates, active_account):
    rates(auth_login="1000/min", auth_login_target="2/min")
    _attempt(api_client, "Active@Tara.Local", "WrongPassw0rd!", "10.0.0.1")
    _attempt(api_client, "  active@tara.local ", "WrongPassw0rd!", "10.0.0.2")
    assert _attempt(api_client, "ACTIVE@tara.local", "DevPassw0rd!", "10.0.0.3").status_code == 429


def test_ip_throttle_still_applies(api_client, rates, active_account):
    rates(auth_login="2/min", auth_login_target="1000/min")
    _attempt(api_client, "a@tara.local", "WrongPassw0rd!", "10.0.0.7")
    _attempt(api_client, "b@tara.local", "WrongPassw0rd!", "10.0.0.7")
    assert _attempt(api_client, "c@tara.local", "WrongPassw0rd!", "10.0.0.7").status_code == 429


def test_failure_lockout_still_applies(api_client, rates, active_account):
    rates(auth_login="1000/min", auth_login_target="1000/min")
    for n in range(10):
        _attempt(api_client, active_account.email, "WrongPassw0rd!", f"10.1.0.{n}")
    # Locked even with the right password.
    resp = _attempt(api_client, active_account.email, "DevPassw0rd!", "10.1.1.1")
    assert resp.status_code == 429


def test_cache_key_never_contains_the_raw_email():
    request = APIRequestFactory().post("/", {"email": "Secret.User@tara.local"}, format="json")
    from rest_framework.parsers import JSONParser
    from rest_framework.request import Request

    key = LoginTargetThrottle().get_cache_key(Request(request, parsers=[JSONParser()]), None)
    assert key is not None
    assert "secret.user" not in key.lower()
    assert email_ident("secret.user@tara.local") in key


def test_requests_without_email_are_not_target_throttled():
    assert email_ident("") is None
    assert email_ident(None) is None
    assert email_ident(["a@b.c"]) is None
