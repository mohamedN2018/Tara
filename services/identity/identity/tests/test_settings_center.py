"""Settings centre (plan 08 wave 3C): two-factor sign-in with recovery codes,
login activity, recognised devices and new-device alerts, deactivation and
reactivation, account preferences on /me/, the presence claim, and the
birthday and gender others may see."""

from __future__ import annotations

from datetime import date

import jwt
import pytest
from django.core import mail
from django.urls import reverse

from identity import account_center, two_factor
from identity.models import Account, AccountRole, Device, OutboxEvent, SecurityEvent, UserSession
from tara_common.exceptions import TaraAPIError

pytestmark = pytest.mark.django_db

PASSWORD = "DevPassw0rd!"


def _login(client, email, password=PASSWORD, ua="pytest-browser/1.0", **extra):
    return client.post(
        reverse("identity:login"),
        {"identifier": email, "password": password, **extra},
        format="json",
        HTTP_USER_AGENT=ua,
    )


def _auth(client, account, **extra):
    resp = _login(client, account.email, **extra)
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access_token']}")
    return data


def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def _enable_2fa(client, account) -> tuple[bytes, list[str]]:
    setup = client.post(reverse("identity:me-2fa-setup"), {"password": PASSWORD}, format="json")
    assert setup.status_code == 200, setup.content
    secret = two_factor.decrypt_secret(account.twofactorsecret.secret_enc)
    assert secret is not None
    assert setup.json()["data"]["otpauth_uri"].startswith("otpauth://totp/Tara:")
    code = two_factor.totp_at(secret, two_factor.current_step())
    confirm = client.post(reverse("identity:me-2fa-confirm"), {"code": code}, format="json")
    assert confirm.status_code == 200, confirm.content
    body = confirm.json()["data"]
    assert body["enabled"] is True and len(body["recovery_codes"]) == 10
    return secret, body["recovery_codes"]


# ---- TOTP primitives -----------------------------------------------------------


def test_totp_matches_rfc6238_vector():
    # RFC 6238 appendix B, SHA-1, T = 59 s -> 94287082 (8 digits); we use the last 6.
    secret = b"12345678901234567890"
    assert two_factor.totp_at(secret, 59 // 30) == "287082"
    assert two_factor.matching_step(secret, "287 082", now=59) == 1
    assert two_factor.matching_step(secret, "000000", now=59) is None


def test_secret_is_encrypted_at_rest(api_client, active_account):
    _auth(api_client, active_account)
    _enable_2fa(api_client, active_account)
    row = active_account.twofactorsecret
    row.refresh_from_db()
    assert b"Tara" not in bytes(row.secret_enc)
    assert len(bytes(row.secret_enc)) > 40  # a Fernet token, not 20 raw bytes


# ---- two-factor sign-in -----------------------------------------------------------


def test_setup_needs_the_current_password(api_client, active_account):
    _auth(api_client, active_account)
    resp = api_client.post(reverse("identity:me-2fa-setup"), {"password": "wrong"}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["details"][0]["code"] == "invalid_password"


def test_login_with_2fa_requires_a_code_and_rejects_reuse(api_client, active_account):
    _auth(api_client, active_account)
    secret, _ = _enable_2fa(api_client, active_account)
    api_client.credentials()

    resp = _login(api_client, active_account.email)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "two_factor_required"

    assert _login(api_client, active_account.email, otp="123456").json()["error"]["code"] in {
        "two_factor_invalid"
    }

    # The confirm step spent the current step; the next one is accepted once.
    code = two_factor.totp_at(secret, two_factor.current_step() + 1)
    assert _login(api_client, active_account.email, otp=code).status_code == 200
    again = _login(api_client, active_account.email, otp=code)
    assert again.status_code == 401 and again.json()["error"]["code"] == "two_factor_invalid"


def test_recovery_code_works_exactly_once(api_client, active_account):
    _auth(api_client, active_account)
    _, codes = _enable_2fa(api_client, active_account)
    api_client.credentials()
    assert _login(api_client, active_account.email, otp=codes[0].upper()).status_code == 200
    assert _login(api_client, active_account.email, otp=codes[0]).status_code == 401
    status = two_factor.status(active_account)
    assert status["recovery_codes_remaining"] == 9
    assert SecurityEvent.objects.filter(
        account=active_account, type="two_factor_recovery_used"
    ).exists()


def test_disable_needs_password_and_a_code(
    api_client, active_account, django_capture_on_commit_callbacks
):
    _auth(api_client, active_account)
    with django_capture_on_commit_callbacks(execute=True):
        secret, codes = _enable_2fa(api_client, active_account)
    url = reverse("identity:me-2fa-disable")
    assert (
        api_client.post(url, {"password": PASSWORD, "code": "000000"}, format="json").status_code
        == 400
    )
    assert (
        api_client.post(url, {"password": "nope", "code": codes[1]}, format="json").status_code
        == 400
    )
    with django_capture_on_commit_callbacks(execute=True):
        resp = api_client.post(url, {"password": PASSWORD, "code": codes[1]}, format="json")
    assert resp.status_code == 200 and resp.json()["data"]["enabled"] is False
    api_client.credentials()
    assert _login(api_client, active_account.email).status_code == 200
    subjects = [m.subject for m in mail.outbox]
    assert "Two-factor authentication turned on" in subjects
    assert "Two-factor authentication turned off" in subjects


def test_regenerating_recovery_codes_retires_the_old_ones(api_client, active_account):
    _auth(api_client, active_account)
    _, old = _enable_2fa(api_client, active_account)
    resp = api_client.post(
        reverse("identity:me-2fa-recovery-codes"), {"password": PASSWORD}, format="json"
    )
    new = resp.json()["data"]["recovery_codes"]
    assert set(new).isdisjoint(old)
    api_client.credentials()
    assert _login(api_client, active_account.email, otp=old[0]).status_code == 401
    assert _login(api_client, active_account.email, otp=new[0]).status_code == 200


def test_me_reports_two_factor(api_client, active_account):
    _auth(api_client, active_account)
    assert api_client.get(reverse("identity:me")).json()["data"]["two_factor_enabled"] is False
    _enable_2fa(api_client, active_account)
    assert api_client.get(reverse("identity:me")).json()["data"]["two_factor_enabled"] is True


def test_staff_without_2fa_get_no_roles_when_enforced(api_client, active_account, settings):
    AccountRole.objects.create(account=active_account, role=AccountRole.Role.MODERATOR)
    settings.STAFF_REQUIRE_2FA = True
    data = _auth(api_client, active_account)
    assert _claims(data["access_token"])["roles"] == []
    secret, _ = _enable_2fa(api_client, active_account)
    api_client.credentials()
    code = two_factor.totp_at(secret, two_factor.current_step() + 1)
    data = _auth(api_client, active_account, otp=code)
    assert _claims(data["access_token"])["roles"] == ["moderator"]


# ---- login activity, devices, alerts -----------------------------------------------


def test_activity_lists_own_security_events_only(api_client, active_account):
    other = Account.objects.create_user(
        email="other@tara.local", password=PASSWORD, status=Account.Status.ACTIVE
    )
    _login(api_client, active_account.email, password="wrong")
    _login(api_client, other.email)
    _auth(api_client, active_account)
    body = api_client.get(reverse("identity:me-security-activity")).json()["data"]
    types = [row["type"] for row in body["results"]]
    assert "login_succeeded" in types and "login_failed" in types
    assert set(body["results"][0]) == {"id", "type", "ip_region", "created_at"}
    assert SecurityEvent.objects.filter(account=other).exists()
    ids = {row["id"] for row in body["results"]}
    assert not ids & {str(e.id) for e in SecurityEvent.objects.filter(account=other)}


def test_new_device_sends_an_alert_but_not_the_first_one(
    api_client, active_account, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        _auth(api_client, active_account, ua="first-browser")
    assert not [m for m in mail.outbox if m.subject.startswith("New sign-in")]
    with django_capture_on_commit_callbacks(execute=True):
        _auth(api_client, active_account, ua="first-browser")  # same device: nothing
    assert not [m for m in mail.outbox if m.subject.startswith("New sign-in")]
    with django_capture_on_commit_callbacks(execute=True):
        _auth(api_client, active_account, ua="second-browser")
    alerts = [m for m in mail.outbox if m.subject.startswith("New sign-in")]
    assert len(alerts) == 1 and "second-browser" in alerts[0].body
    assert (
        SecurityEvent.objects.filter(account=active_account, type="login_new_device").count() == 2
    )


def test_login_alerts_can_be_turned_off(
    api_client, active_account, django_capture_on_commit_callbacks
):
    _auth(api_client, active_account, ua="first-browser")
    resp = api_client.patch(reverse("identity:me"), {"login_alerts": False}, format="json")
    assert resp.status_code == 200 and resp.json()["data"]["login_alerts"] is False
    with django_capture_on_commit_callbacks(execute=True):
        _auth(api_client, active_account, ua="another-browser")
    assert not [m for m in mail.outbox if m.subject.startswith("New sign-in")]


def test_devices_list_and_remove(api_client, active_account):
    from rest_framework.test import APIClient

    other_client = APIClient()
    _auth(other_client, active_account, ua="phone-browser")
    _auth(api_client, active_account, ua="desk-browser")
    devices = api_client.get(reverse("identity:me-devices")).json()["data"]
    by_label = {d["label"]: d for d in devices}
    assert by_label["desk-browser"]["is_current"] is True
    assert by_label["phone-browser"]["active_sessions"] == 1

    current = by_label["desk-browser"]["id"]
    assert api_client.delete(reverse("identity:me-device", args=[current])).status_code == 400
    phone = by_label["phone-browser"]["id"]
    assert api_client.delete(reverse("identity:me-device", args=[phone])).status_code == 204
    assert not Device.objects.filter(id=phone).exists()
    assert other_client.get(reverse("identity:me-devices")).status_code in {200, 401}
    assert (
        UserSession.objects.filter(
            account=active_account, device__isnull=True, revoked_at__isnull=True
        ).count()
        == 0
    )
    # Somebody else's device is a 404, never a 403.
    stranger = Account.objects.create_user(
        email="x@tara.local", password=PASSWORD, status=Account.Status.ACTIVE
    )
    theirs = Device.objects.create(account=stranger, label="x")
    assert api_client.delete(reverse("identity:me-device", args=[theirs.id])).status_code == 404


# ---- deactivation ------------------------------------------------------------------


def test_deactivate_signs_out_and_sign_in_reactivates(api_client, active_account):
    data = _auth(api_client, active_account)
    url = reverse("identity:me-deactivate")
    assert api_client.post(url, {"password": "wrong"}, format="json").status_code == 400
    resp = api_client.post(url, {"password": PASSWORD}, format="json")
    assert resp.status_code == 200, resp.content
    active_account.refresh_from_db()
    assert active_account.status == Account.Status.DEACTIVATED
    assert not UserSession.objects.filter(account=active_account, revoked_at__isnull=True).exists()
    refresh = api_client.post(
        reverse("identity:refresh"), {"refresh_token": data["refresh_token"]}, format="json"
    )
    assert refresh.status_code == 401
    assert OutboxEvent.objects.filter(event_type="account.deactivated").count() == 1

    api_client.credentials()
    assert _login(api_client, active_account.email, password="wrong").status_code == 401
    assert _login(api_client, active_account.email).status_code == 200
    active_account.refresh_from_db()
    assert active_account.status == Account.Status.ACTIVE
    assert OutboxEvent.objects.filter(event_type="account.reactivated").count() == 1


def test_deactivated_account_with_2fa_needs_the_code_to_come_back(api_client, active_account):
    _auth(api_client, active_account)
    secret, _ = _enable_2fa(api_client, active_account)
    api_client.post(reverse("identity:me-deactivate"), {"password": PASSWORD}, format="json")
    api_client.credentials()
    assert _login(api_client, active_account.email).status_code == 401
    active_account.refresh_from_db()
    assert active_account.status == Account.Status.DEACTIVATED
    code = two_factor.totp_at(secret, two_factor.current_step() + 1)
    assert _login(api_client, active_account.email, otp=code).status_code == 200


def test_suspended_account_is_not_reactivated_by_sign_in(api_client, active_account):
    active_account.status = Account.Status.SUSPENDED
    active_account.save()
    resp = _login(api_client, active_account.email)
    assert resp.status_code == 403
    with pytest.raises(TaraAPIError):
        account_center.deactivate(active_account, password=PASSWORD)


def test_deactivation_events_obey_the_flag(api_client, active_account, settings):
    settings.IDENTITY_EMIT_ACCOUNT_ACTION_EVENTS = False
    _auth(api_client, active_account)
    api_client.post(reverse("identity:me-deactivate"), {"password": PASSWORD}, format="json")
    assert not OutboxEvent.objects.filter(event_type="account.deactivated").exists()


# ---- preferences on /me/ and the presence claim ---------------------------------------


def test_me_patch_preferences_and_presence_claim(api_client, active_account):
    data = _auth(api_client, active_account)
    assert _claims(data["access_token"])["show_presence"] is True
    resp = api_client.patch(
        reverse("identity:me"),
        {"language": "ar", "theme": "dark", "show_presence": False},
        format="json",
    )
    body = resp.json()["data"]
    assert (body["language"], body["theme"], body["show_presence"]) == ("ar", "dark", False)
    refreshed = api_client.post(
        reverse("identity:refresh"), {"refresh_token": data["refresh_token"]}, format="json"
    ).json()["data"]
    assert _claims(refreshed["access_token"])["show_presence"] is False


def test_me_patch_gender_and_visibility(api_client, active_account):
    _auth(api_client, active_account)
    url = reverse("identity:me")
    bad = api_client.patch(url, {"gender": "custom", "gender_custom": "  "}, format="json")
    assert bad.status_code == 400
    ok = api_client.patch(
        url,
        {"gender": "custom", "gender_custom": " non  binary ", "gender_visibility": "friends"},
        format="json",
    ).json()["data"]
    assert (ok["gender"], ok["gender_custom"], ok["gender_visibility"]) == (
        "custom",
        "non binary",
        "friends",
    )
    ok = api_client.patch(url, {"gender": "female"}, format="json").json()["data"]
    assert ok["gender_custom"] == ""
    # The date of birth is read-only here.
    api_client.patch(url, {"date_of_birth": "2015-01-01"}, format="json")
    active_account.refresh_from_db()
    assert active_account.date_of_birth is None
    assert (
        api_client.patch(url, {"birthday_visibility": "everyone"}, format="json").status_code == 400
    )


# ---- birthday and gender, as others see them -----------------------------------------


def _person(**fields) -> Account:
    return Account.objects.create_user(
        email=f"p{Account.objects.count()}@tara.local",
        password=PASSWORD,
        status=Account.Status.ACTIVE,
        date_of_birth=date(1990, 7, 14),
        gender="female",
        **fields,
    )


def test_personal_details_respect_each_audience(api_client, active_account, monkeypatch):
    owner = _person(birthday_visibility="friends", gender_visibility="only_me")
    url = reverse("identity:personal-details", args=[owner.id])
    friends = {"value": False}
    monkeypatch.setattr(
        account_center,
        "_relationship",
        lambda a, b: {"are_friends": friends["value"], "blocked_either_way": False},
    )

    _auth(api_client, active_account)
    body = api_client.get(url).json()["data"]
    assert body["birthday"] is None and body["gender"] is None

    friends["value"] = True
    body = api_client.get(url).json()["data"]
    assert body["birthday"] == {"month": 7, "day": 14}  # never the year
    assert body["gender"] is None

    api_client.credentials()
    _auth(api_client, owner)
    body = api_client.get(url).json()["data"]
    assert body["gender"] == {"value": "female", "custom": None}


def test_personal_details_of_unusable_account_is_404(api_client, active_account):
    owner = _person()
    owner.status = Account.Status.DEACTIVATED
    owner.save()
    _auth(api_client, active_account)
    url = reverse("identity:personal-details", args=[owner.id])
    assert api_client.get(url).status_code == 404


def test_friend_lookup_fails_closed(monkeypatch, settings):
    settings.GRAPH_INTERNAL_URL = "http://127.0.0.1:9"  # nothing listens there
    settings.GRAPH_CALL_TIMEOUT = 0.2
    assert (
        account_center._relationship(
            "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
        )
        is None
    )


@pytest.mark.parametrize("visibility", ["friends", "only_me"])
def test_personal_details_across_a_block_is_404(
    api_client, active_account, monkeypatch, visibility
):
    """Either way, and whatever the audiences: the account does not exist for the viewer."""
    owner = _person(birthday_visibility=visibility, gender_visibility=visibility)
    monkeypatch.setattr(
        account_center,
        "_relationship",
        lambda a, b: {"are_friends": True, "blocked_either_way": True},
    )
    _auth(api_client, active_account)
    url = reverse("identity:personal-details", args=[owner.id])
    assert api_client.get(url).status_code == 404


def test_personal_details_with_graph_down_show_nothing(api_client, active_account, monkeypatch):
    owner = _person(birthday_visibility="friends", gender_visibility="friends")
    monkeypatch.setattr(account_center, "_relationship", lambda a, b: None)
    _auth(api_client, active_account)
    body = api_client.get(reverse("identity:personal-details", args=[owner.id])).json()["data"]
    assert body["birthday"] is None and body["gender"] is None
