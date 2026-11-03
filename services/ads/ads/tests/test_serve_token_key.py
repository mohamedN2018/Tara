"""Roadmap 1.0e: serve tokens are signed with a secret only ads holds."""

import hashlib
import hmac
import time
import uuid
from io import StringIO
from unittest.mock import Mock

import jwt
import pytest
from django.core.checks import ERROR, WARNING
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import SystemCheckError

from ads import checks, serve_tokens
from ads.tests.test_ads import _acct, _event, _make_active_creative, _spent
from tara_common.exceptions import TaraAPIError

STRONG_SECRET = "9f" * 32


def _claims(viewer: str, creative_id) -> dict:
    now = int(time.time())
    return {
        "aud": "ad-serve",
        "sub": str(viewer),
        "cid": str(creative_id),
        "pl": "feed",
        "iat": now,
        "exp": now + 600,
        "jti": uuid.uuid4().hex,
    }


def _old_shared_key(settings) -> str:
    """The key every service could compute before 1.0e."""
    return hmac.new(
        settings.TARA_INTERNAL_JWT_SECRET.encode(), b"ad-serve-token", hashlib.sha256
    ).hexdigest()


# ---- signing and verifying --------------------------------------------------------


@pytest.mark.django_db
def test_token_signed_with_the_old_shared_key_is_rejected(client_for, settings):
    campaign, creative = _make_active_creative(_acct())
    viewer = _acct()
    client = client_for(viewer)
    for key in (_old_shared_key(settings), settings.TARA_INTERNAL_JWT_SECRET):
        forged = jwt.encode(_claims(viewer, creative.id), key, algorithm="HS256")
        assert _event(client, creative, forged, "click").status_code == 403
        assert _event(client, creative, forged, "impression").status_code == 403
    assert _spent(campaign) == 0

    # A token ads itself issued still pays.
    token = serve_tokens.issue(viewer, creative.id, "feed")
    assert _event(client, creative, token, "click").status_code == 202
    assert _spent(campaign) > 0


@pytest.mark.django_db
def test_dev_fallback_key_is_not_the_old_key_and_warns_once(client_for, settings, monkeypatch):
    settings.ADS_SERVE_TOKEN_SECRET = ""
    monkeypatch.setattr(serve_tokens, "_warned_dev_key", False)
    warning = Mock()
    monkeypatch.setattr(serve_tokens.logger, "warning", warning)
    campaign, creative = _make_active_creative(_acct())
    viewer = _acct()
    client = client_for(viewer)

    forged = jwt.encode(_claims(viewer, creative.id), _old_shared_key(settings), algorithm="HS256")
    assert _event(client, creative, forged, "click").status_code == 403
    assert _spent(campaign) == 0

    token = serve_tokens.issue(viewer, creative.id, "feed")
    assert _event(client, creative, token, "click").status_code == 202
    assert _spent(campaign) > 0
    assert warning.call_count == 1


def test_rotating_the_secret_invalidates_outstanding_tokens(settings):
    viewer, creative_id = _acct(), str(uuid.uuid4())
    token = serve_tokens.issue(viewer, creative_id, "feed")
    assert serve_tokens.verify(token, viewer, creative_id)["cid"] == creative_id

    settings.ADS_SERVE_TOKEN_SECRET = "another-ads-serve-token-secret-fedcba9876543210"
    with pytest.raises(TaraAPIError):
        serve_tokens.verify(token, viewer, creative_id)


def test_production_never_signs_or_verifies_without_the_ads_secret(settings):
    settings.TARA_ENV = "production"
    settings.ADS_SERVE_TOKEN_SECRET = ""
    viewer, creative_id = _acct(), str(uuid.uuid4())
    with pytest.raises(ImproperlyConfigured):
        serve_tokens.issue(viewer, creative_id, "feed")
    # Not even a token signed with the development fallback key gets through.
    forged = jwt.encode(_claims(viewer, creative_id), serve_tokens._dev_key(), algorithm="HS256")
    with pytest.raises(ImproperlyConfigured):
        serve_tokens.verify(forged, viewer, creative_id)


@pytest.mark.parametrize("env", ["development", "production"])
def test_reusing_the_internal_secret_is_refused_everywhere(settings, env):
    settings.TARA_ENV = env
    settings.ADS_SERVE_TOKEN_SECRET = settings.TARA_INTERNAL_JWT_SECRET
    with pytest.raises(ImproperlyConfigured):
        serve_tokens.issue(_acct(), str(uuid.uuid4()), "feed")
    [message] = checks.check_serve_token_secret_is_ads_only()
    assert (message.id, message.level) == ("ads.E003", ERROR)


# ---- system checks ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("secret", "expected"),
    [
        ("", ["ads.E002"]),
        ("short-but-real", ["ads.E004"]),
        ("dev-only-ads-serve-token-secret-change-me", ["ads.E004"]),
        ("__REPLACE_ME__" + "x" * 40, ["ads.E004"]),
        ("__GENERATED__" + "x" * 40, ["ads.E004"]),
        (STRONG_SECRET, []),
    ],
)
def test_production_secret_deploy_check(settings, secret, expected):
    settings.TARA_ENV = "production"
    settings.ADS_SERVE_TOKEN_SECRET = secret
    messages = checks.check_serve_token_secret()
    assert [m.id for m in messages] == expected
    assert all(m.level == ERROR for m in messages)


def test_production_secret_must_not_reuse_the_django_secret_key(settings):
    settings.TARA_ENV = "production"
    settings.SECRET_KEY = STRONG_SECRET
    settings.ADS_SERVE_TOKEN_SECRET = STRONG_SECRET
    assert [m.id for m in checks.check_serve_token_secret()] == ["ads.E005"]


def test_missing_secret_is_a_warning_in_development_only(settings):
    settings.TARA_ENV = "development"
    settings.ADS_SERVE_TOKEN_SECRET = ""
    assert checks.check_serve_token_secret() == []
    [message] = checks.check_serve_token_secret_is_ads_only()
    assert (message.id, message.level) == ("ads.W002", WARNING)

    # In production the deploy check's E002 covers it instead.
    settings.TARA_ENV = "production"
    assert checks.check_serve_token_secret_is_ads_only() == []


def test_dev_placeholder_is_accepted_outside_production(settings):
    settings.TARA_ENV = "development"
    settings.ADS_SERVE_TOKEN_SECRET = "dev-only-ads-serve-token-secret-change-me"
    assert checks.check_serve_token_secret() == []
    assert checks.check_serve_token_secret_is_ads_only() == []


def test_production_deploy_gate_fails_without_the_secret(settings):
    settings.TARA_ENV = "production"
    settings.DEBUG = True  # keeps the shared tara.E00x checks out of this test
    settings.ADS_SERVING_ENABLED = False
    settings.ADS_SERVE_TOKEN_SECRET = ""
    with pytest.raises(SystemCheckError, match=r"ads\.E002"):
        call_command("check", deploy=True, fail_level="ERROR", stdout=StringIO(), stderr=StringIO())
