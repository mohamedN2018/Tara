"""Fix track A (3C): account deletion with a 30-day grace, the separate
throttle scope for 2FA and lifecycle endpoints, Google sign-in's second factor
spending the lockout budget, and the presence event."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from identity import account_center, two_factor
from identity.models import (
    Account,
    AccountRole,
    Device,
    OutboxEvent,
    SecurityEvent,
    TwoFactorSecret,
    UserSession,
)
from identity.tasks import purge_scheduled_deletions
from tara_common.exceptions import TaraAPIError

pytestmark = pytest.mark.django_db

PASSWORD = "DevPassw0rd!"
SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")


def _login(client, email, password=PASSWORD, **extra):
    return client.post(
        reverse("identity:login"),
        {"identifier": email, "password": password, **extra},
        format="json",
        HTTP_USER_AGENT="pytest-browser/1.0",
    )


def _auth(client, account, **extra):
    resp = _login(client, account.email, **extra)
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access_token']}")
    return data


def _payload_matches(event_type: str, payload: dict) -> None:
    path = SCHEMAS / f"{event_type}.v1.json"
    if not path.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    schema = json.loads(path.read_text())
    assert set(schema["required"]) <= set(payload) <= set(schema["properties"])


# ---- delete account ----------------------------------------------------------------


def test_delete_needs_the_password_and_schedules_30_days(
    api_client, active_account, django_capture_on_commit_callbacks
):
    data = _auth(api_client, active_account)
    url = reverse("identity:me-delete")
    assert api_client.post(url, {"password": "wrong"}, format="json").status_code == 400
    active_account.refresh_from_db()
    assert active_account.status == Account.Status.ACTIVE

    with django_capture_on_commit_callbacks(execute=True):
        resp = api_client.post(url, {"password": PASSWORD}, format="json")
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert body["status"] == "deletion_scheduled"
    active_account.refresh_from_db()
    assert active_account.status == Account.Status.DEACTIVATED
    due = active_account.deletion_scheduled_for
    assert due is not None
    assert timedelta(days=29, hours=23) < due - timezone.now() <= timedelta(days=30)
    # Signed out everywhere, and hidden like a deactivated account meanwhile.
    assert not UserSession.objects.filter(account=active_account, revoked_at__isnull=True).exists()
    refresh = api_client.post(
        reverse("identity:refresh"), {"refresh_token": data["refresh_token"]}, format="json"
    )
    assert refresh.status_code == 401
    assert OutboxEvent.objects.filter(event_type="account.deactivated").count() == 1
    assert not OutboxEvent.objects.filter(event_type="account.deleted").exists()
    assert SecurityEvent.objects.filter(
        account=active_account, type="account_deletion_scheduled"
    ).exists()
    assert any("will be deleted" in m.subject for m in mail.outbox)


def test_google_only_account_types_delete(api_client, active_account):
    active_account.set_unusable_password()
    active_account.save()
    with pytest.raises(TaraAPIError):
        account_center.schedule_deletion(active_account, password="", confirm="nope")
    account_center.schedule_deletion(active_account, password="", confirm="delete")
    active_account.refresh_from_db()
    assert active_account.deletion_scheduled_for is not None


def test_sign_in_during_the_grace_cancels_the_deletion(api_client, active_account):
    _auth(api_client, active_account)
    api_client.post(reverse("identity:me-delete"), {"password": PASSWORD}, format="json")
    api_client.credentials()
    assert _login(api_client, active_account.email).status_code == 200
    active_account.refresh_from_db()
    assert active_account.status == Account.Status.ACTIVE
    assert active_account.deletion_scheduled_for is None
    assert OutboxEvent.objects.filter(event_type="account.reactivated").count() == 1
    assert SecurityEvent.objects.filter(
        account=active_account, type="account_deletion_cancelled"
    ).exists()
    # Nothing is erased later.
    assert purge_scheduled_deletions() == 0
    active_account.refresh_from_db()
    assert active_account.status == Account.Status.ACTIVE


def test_purge_erases_only_accounts_past_their_grace(api_client, active_account):
    other = Account.objects.create_user(
        email="other@tara.local", password=PASSWORD, status=Account.Status.ACTIVE
    )
    _auth(api_client, active_account)
    _enable = api_client.post(
        reverse("identity:me-2fa-setup"), {"password": PASSWORD}, format="json"
    )
    assert _enable.status_code == 200
    AccountRole.objects.create(account=active_account, role="moderator")
    account_center.schedule_deletion(active_account, password=PASSWORD)
    account_center.schedule_deletion(other, password=PASSWORD)
    Account.objects.filter(pk=other.pk).update(
        deletion_scheduled_for=timezone.now() + timedelta(days=3)
    )

    assert purge_scheduled_deletions() == 0  # nobody is due yet
    Account.objects.filter(pk=active_account.pk).update(
        deletion_scheduled_for=timezone.now() - timedelta(seconds=1)
    )
    old_email = active_account.email
    assert purge_scheduled_deletions() == 1
    assert purge_scheduled_deletions() == 0  # idempotent

    gone = Account.objects.get(pk=active_account.pk)
    assert gone.status == Account.Status.DELETED
    assert gone.email != old_email and gone.email.endswith("@deleted.invalid")
    assert not gone.has_usable_password() and not gone.is_active
    assert (gone.phone, gone.date_of_birth, gone.gender) == ("", None, "")
    assert gone.deleted_at is not None and gone.deletion_scheduled_for is None
    assert not UserSession.objects.filter(account=gone).exists()
    assert not Device.objects.filter(account=gone).exists()
    assert not TwoFactorSecret.objects.filter(account=gone).exists()
    assert not AccountRole.objects.filter(account=gone).exists()
    assert not SecurityEvent.objects.filter(account=gone).exclude(metadata={}).exists()
    events = OutboxEvent.objects.filter(event_type="account.deleted")
    assert events.count() == 1
    payload = events.get().payload["payload"]
    assert payload == {"account_id": str(gone.pk)}
    _payload_matches("account.deleted", payload)

    other.refresh_from_db()
    assert other.status == Account.Status.DEACTIVATED  # still in its grace
    # The erased account cannot sign in, and its old email can register again.
    assert _login(api_client, old_email).status_code == 401
    assert not Account.objects.filter(email=old_email).exists()


def test_deleted_event_obeys_the_flag(active_account, settings):
    settings.IDENTITY_EMIT_ACCOUNT_ACTION_EVENTS = False
    account_center.schedule_deletion(active_account, password=PASSWORD)
    Account.objects.filter(pk=active_account.pk).update(
        deletion_scheduled_for=timezone.now() - timedelta(seconds=1)
    )
    assert purge_scheduled_deletions() == 1
    assert not OutboxEvent.objects.filter(event_type="account.deleted").exists()


def test_only_an_active_account_can_be_deleted(active_account):
    active_account.status = Account.Status.SUSPENDED
    active_account.save()
    with pytest.raises(TaraAPIError):
        account_center.schedule_deletion(active_account, password=PASSWORD)


# ---- throttle scopes -----------------------------------------------------------------


def test_2fa_and_lifecycle_endpoints_do_not_spend_the_password_scope():
    from identity import security_views, settings_views

    for view in (
        settings_views.TwoFactorSetupView,
        settings_views.TwoFactorConfirmView,
        settings_views.TwoFactorDisableView,
        settings_views.RecoveryCodesView,
        settings_views.DeactivateView,
        settings_views.DeleteAccountView,
    ):
        assert view.throttle_scope == "account_security", view
    assert security_views.ChangePasswordView.throttle_scope == "auth_password"


@pytest.mark.parametrize(
    ("value", "rate"), [("7/hour", "7/hour"), ("", "30/hour"), (None, "30/hour")]
)
def test_account_security_rate_comes_from_the_env(monkeypatch, value, rate):
    """Like every other rate; compose passes an unset variable as "", which is no rate."""
    import importlib.util

    from config import settings as config_settings

    if value is None:
        monkeypatch.delenv("ACCOUNT_SECURITY_RATE", raising=False)
    else:
        monkeypatch.setenv("ACCOUNT_SECURITY_RATE", value)
    spec = importlib.util.spec_from_file_location("_settings_copy", config_settings.__file__)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)  # a copy: the live settings stay untouched
    assert fresh.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["account_security"] == rate


def test_mistyped_2fa_codes_leave_the_password_change_open(api_client, active_account, settings):
    """Setup plus several wrong codes used to exhaust the 5/hour password scope."""
    import copy

    from rest_framework.throttling import SimpleRateThrottle

    rest = copy.deepcopy(settings.REST_FRAMEWORK)
    rest["DEFAULT_THROTTLE_RATES"]["auth_password"] = "2/hour"
    settings.REST_FRAMEWORK = rest
    old = SimpleRateThrottle.THROTTLE_RATES
    SimpleRateThrottle.THROTTLE_RATES = rest["DEFAULT_THROTTLE_RATES"]
    try:
        _auth(api_client, active_account)
        api_client.post(reverse("identity:me-2fa-setup"), {"password": PASSWORD}, format="json")
        for _ in range(4):
            wrong = api_client.post(
                reverse("identity:me-2fa-confirm"), {"code": "000000"}, format="json"
            )
            assert wrong.status_code != 429
        change = api_client.post(
            reverse("identity:me-password"),
            {"current_password": "wrong", "new_password": "AnotherPassw0rd!"},
            format="json",
        )
        assert change.status_code != 429
    finally:
        SimpleRateThrottle.THROTTLE_RATES = old


# ---- Google sign-in's second factor and the lockout -----------------------------------


def _google_account(monkeypatch):
    from identity import account_security
    from identity.google import GoogleIdentity
    from identity.models import SocialIdentity

    account = Account.objects.create_user(
        email="g@tara.local", password=None, status=Account.Status.ACTIVE, email_verified=True
    )
    SocialIdentity.objects.create(
        account=account,
        provider=SocialIdentity.Provider.GOOGLE,
        subject="sub-1",
        email=account.email,
    )
    monkeypatch.setattr(
        account_security,
        "_verified_google",
        lambda credential, signed_in=False: GoogleIdentity(
            subject="sub-1", email=account.email, name="G"
        ),
    )
    secret = b"0123456789abcdefghij"
    TwoFactorSecret.objects.create(
        account=account, secret_enc=two_factor.encrypt_secret(secret), confirmed_at=timezone.now()
    )
    return account, secret


def test_wrong_google_otp_counts_toward_the_lockout(monkeypatch, settings):
    from identity import account_security, services

    account, secret = _google_account(monkeypatch)
    for _ in range(services.LOGIN_MAX_FAILURES):
        with pytest.raises(two_factor.TwoFactorInvalid):
            account_security.google_sign_in(credential="x", otp="000000")
    good = two_factor.totp_at(secret, two_factor.current_step())
    with pytest.raises(Exception) as locked:
        account_security.google_sign_in(credential="x", otp=good)
    assert getattr(locked.value, "code", "") == "throttled"
    # The password path for the same email is locked too: one budget.
    with pytest.raises(Exception) as also:
        services.login(identifier=account.email, password="whatever")
    assert getattr(also.value, "code", "") == "throttled"


def test_right_google_otp_clears_the_failures(monkeypatch):
    from django.core.cache import cache

    from identity import account_security, services

    account, secret = _google_account(monkeypatch)
    with pytest.raises(two_factor.TwoFactorInvalid):
        account_security.google_sign_in(credential="x", otp="000000")
    key = services.login_lock_key(account.email)
    assert cache.get(key) == 1
    good = two_factor.totp_at(secret, two_factor.current_step())
    account_security.google_sign_in(credential="x", otp=good)
    assert cache.get(key) is None


# ---- presence event ---------------------------------------------------------------------


def test_presence_change_emits_the_event_once(api_client, active_account):
    _auth(api_client, active_account)
    url = reverse("identity:me")
    api_client.patch(url, {"show_presence": False}, format="json")
    api_client.patch(url, {"show_presence": False}, format="json")  # no change, no event
    api_client.patch(url, {"theme": "dark"}, format="json")
    events = OutboxEvent.objects.filter(event_type="account.presence.updated")
    assert events.count() == 1
    payload = events.get().payload["payload"]
    assert payload == {"account_id": str(active_account.id), "show_presence": False}
    _payload_matches("account.presence.updated", payload)
    api_client.patch(url, {"show_presence": True}, format="json")
    assert events.count() == 2
