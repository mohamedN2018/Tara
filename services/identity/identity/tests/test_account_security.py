"""Change password, change email, and the security overview."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from identity import services
from identity.models import (
    Account,
    EmailChangeRequest,
    OutboxEvent,
    PasswordReset,
    SecurityEvent,
    UserSession,
)

pytestmark = pytest.mark.django_db

PASSWORD = "DevPassw0rd!"
NEW_PASSWORD = "Fresh-Passw0rd-42"


def _login(client, email, password=PASSWORD, ip="10.0.0.1"):
    resp = client.post(
        reverse("identity:login"),
        {"email": email, "password": password},
        format="json",
        REMOTE_ADDR=ip,
    )
    return resp


def _auth(client, email, password=PASSWORD):
    resp = _login(client, email, password)
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access_token']}")
    return data


def _token_from(message) -> str:
    match = re.search(r"token=([\w-]+)", message.body)
    assert match, message.body
    return match.group(1)


def _mails_to(address):
    return [m for m in mail.outbox if address in m.to]


# ---- overview ---------------------------------------------------------------


def test_security_overview_requires_auth(api_client):
    assert api_client.get(reverse("identity:me-security")).status_code == 401


def test_security_overview_for_password_account(api_client, active_account):
    _auth(api_client, active_account.email)
    body = api_client.get(reverse("identity:me-security")).json()["data"]
    assert body == {
        "email": active_account.email,
        "email_verified": True,
        "has_password": True,
        "pending_email": None,
        "google": {"linked": False, "email": None, "linked_at": None},
        "phone": None,
        "phone_verified": False,
        "phone_verified_at": None,
    }


# ---- change password --------------------------------------------------------


def test_change_password_requires_auth(api_client):
    resp = api_client.post(
        reverse("identity:me-password"),
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert resp.status_code == 401


def test_change_password_rejects_wrong_current_password(api_client, active_account):
    _auth(api_client, active_account.email)
    resp = api_client.post(
        reverse("identity:me-password"),
        {"current_password": "NotMyPassw0rd!", "new_password": NEW_PASSWORD},
        format="json",
    )
    assert resp.status_code == 400
    detail = resp.json()["error"]["details"][0]
    assert (detail["field"], detail["code"]) == ("current_password", "invalid_password")
    active_account.refresh_from_db()
    assert active_account.check_password(PASSWORD)
    assert SecurityEvent.objects.filter(account=active_account, type="reauth_failed").exists()


def test_change_password_rejects_weak_and_unchanged_passwords(api_client, active_account):
    _auth(api_client, active_account.email)
    url = reverse("identity:me-password")
    weak = api_client.post(
        url, {"current_password": PASSWORD, "new_password": "1234567890"}, format="json"
    )
    assert weak.status_code == 400
    assert weak.json()["error"]["details"][0]["field"] == "new_password"
    assert weak.json()["error"]["details"][0]["code"] == "weak_password"
    same = api_client.post(
        url, {"current_password": PASSWORD, "new_password": PASSWORD}, format="json"
    )
    assert same.status_code == 400
    assert same.json()["error"]["details"][0]["code"] == "same_password"


def test_change_password_revokes_other_sessions_only(
    api_client, active_account, django_capture_on_commit_callbacks
):
    from rest_framework.test import APIClient

    other_device = APIClient()
    other = _login(other_device, active_account.email, ip="10.0.0.2").json()["data"]
    mine = _auth(api_client, active_account.email)

    with django_capture_on_commit_callbacks(execute=True):
        resp = api_client.post(
            reverse("identity:me-password"),
            {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            format="json",
        )
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"]["revoked_sessions"] == 1

    # The other device's refresh token is dead; this session's still rotates.
    dead = other_device.post(
        reverse("identity:refresh"), {"refresh_token": other["refresh_token"]}, format="json"
    )
    assert dead.status_code == 401
    alive = api_client.post(
        reverse("identity:refresh"), {"refresh_token": mine["refresh_token"]}, format="json"
    )
    assert alive.status_code == 200
    assert UserSession.objects.filter(account=active_account, revoked_at__isnull=True).count() == 1

    assert _login(APIClient(), active_account.email, NEW_PASSWORD).status_code == 200
    assert _login(APIClient(), active_account.email, PASSWORD).status_code == 401
    notice = _mails_to(active_account.email)
    assert notice and "password was changed" in notice[-1].subject.lower()


def test_change_password_invalidates_outstanding_reset_links(api_client, active_account):
    services.request_password_reset(email=active_account.email)
    _auth(api_client, active_account.email)
    api_client.post(
        reverse("identity:me-password"),
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert not PasswordReset.objects.filter(
        account=active_account, consumed_at__isnull=True
    ).exists()


def test_account_without_password_must_use_reset_flow(api_client, active_account):
    _auth(api_client, active_account.email)
    active_account.set_unusable_password()
    active_account.save()
    resp = api_client.post(
        reverse("identity:me-password"),
        {"current_password": "", "new_password": NEW_PASSWORD},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["details"][0]["code"] == "no_password"


# ---- change email -----------------------------------------------------------


def _request_change(client, new_email, password=PASSWORD):
    return client.post(
        reverse("identity:me-email"), {"new_email": new_email, "password": password}, format="json"
    )


def _confirm(client, token):
    client_without_auth = client.__class__()
    return client_without_auth.post(
        reverse("identity:email-change-confirm"), {"token": token}, format="json"
    )


def test_change_email_requires_auth(api_client):
    assert _request_change(api_client, "new@tara.local").status_code == 401


def test_change_email_requires_current_password(api_client, active_account):
    _auth(api_client, active_account.email)
    resp = _request_change(api_client, "new@tara.local", password="WrongPassw0rd!")
    assert resp.status_code == 400
    assert resp.json()["error"]["details"][0]["code"] == "invalid_password"
    assert not EmailChangeRequest.objects.exists()


def test_change_email_rejects_same_address(api_client, active_account):
    _auth(api_client, active_account.email)
    resp = _request_change(api_client, active_account.email.upper())
    assert resp.status_code == 400
    assert resp.json()["error"]["details"][0]["code"] == "same_email"


def test_change_email_full_flow(api_client, active_account, django_capture_on_commit_callbacks):
    _auth(api_client, active_account.email)
    with django_capture_on_commit_callbacks(execute=True):
        resp = _request_change(api_client, "New.Address@Tara.local")
    assert resp.status_code == 202
    assert resp.json()["data"]["pending_email"] == "new.address@tara.local"

    # Nothing changes until the new address is proven.
    active_account.refresh_from_db()
    assert active_account.email == "active@tara.local"
    overview = api_client.get(reverse("identity:me-security")).json()["data"]
    assert overview["pending_email"] == "new.address@tara.local"

    to_new = _mails_to("new.address@tara.local")
    to_old = _mails_to("active@tara.local")
    assert len(to_new) == 1 and "/confirm-email?token=" in to_new[0].body
    assert len(to_old) == 1 and "n***@tara.local" in to_old[0].body
    assert "token=" not in to_old[0].body  # the old inbox can't confirm

    with django_capture_on_commit_callbacks(execute=True):
        confirmed = _confirm(api_client, _token_from(to_new[0]))
    assert confirmed.status_code == 200, confirmed.content
    assert confirmed.json()["data"]["email"] == "new.address@tara.local"

    active_account.refresh_from_db()
    assert active_account.email == "new.address@tara.local"
    assert active_account.email_verified is True
    event = OutboxEvent.objects.get(event_type="account.email_changed")
    assert event.payload["payload"]["email"] == "new.address@tara.local"
    assert event.payload["payload"]["previous_email"] == "active@tara.local"
    assert "changed" in _mails_to("active@tara.local")[-1].subject.lower()

    from rest_framework.test import APIClient

    assert _login(APIClient(), "new.address@tara.local").status_code == 200
    assert _login(APIClient(), "active@tara.local").status_code == 401
    # Single use.
    assert _confirm(api_client, _token_from(to_new[0])).status_code == 400


def test_change_email_to_taken_address_does_not_reveal_it(
    api_client, active_account, django_capture_on_commit_callbacks
):
    Account.objects.create_user(email="taken@tara.local", password=PASSWORD)
    _auth(api_client, active_account.email)
    with django_capture_on_commit_callbacks(execute=True):
        taken = _request_change(api_client, "taken@tara.local")
    with django_capture_on_commit_callbacks(execute=True):
        free = _request_change(api_client, "free@tara.local")
    # Same status and shape either way.
    assert taken.status_code == free.status_code == 202
    assert set(taken.json()["data"]) == set(free.json()["data"])
    # The taken address gets a notice, never a working link.
    notice = _mails_to("taken@tara.local")
    assert len(notice) == 1 and "token=" not in notice[0].body


def test_confirm_fails_if_address_was_taken_meanwhile(
    api_client, active_account, django_capture_on_commit_callbacks
):
    _auth(api_client, active_account.email)
    with django_capture_on_commit_callbacks(execute=True):
        _request_change(api_client, "race@tara.local")
    token = _token_from(_mails_to("race@tara.local")[0])
    Account.objects.create_user(email="race@tara.local", password=PASSWORD)
    assert _confirm(api_client, token).status_code == 409
    active_account.refresh_from_db()
    assert active_account.email == "active@tara.local"


def test_new_request_and_cancel_invalidate_old_links(
    api_client, active_account, django_capture_on_commit_callbacks
):
    _auth(api_client, active_account.email)
    with django_capture_on_commit_callbacks(execute=True):
        _request_change(api_client, "first@tara.local")
        _request_change(api_client, "second@tara.local")
    first = _token_from(_mails_to("first@tara.local")[0])
    second = _token_from(_mails_to("second@tara.local")[0])
    assert _confirm(api_client, first).status_code == 400

    assert api_client.delete(reverse("identity:me-email")).status_code == 204
    assert _confirm(api_client, second).status_code == 400
    assert api_client.get(reverse("identity:me-security")).json()["data"]["pending_email"] is None


def test_expired_and_unknown_links_are_rejected(
    api_client, active_account, django_capture_on_commit_callbacks
):
    _auth(api_client, active_account.email)
    with django_capture_on_commit_callbacks(execute=True):
        _request_change(api_client, "late@tara.local")
    token = _token_from(_mails_to("late@tara.local")[0])
    EmailChangeRequest.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert _confirm(api_client, token).status_code == 400
    assert _confirm(api_client, "made-up-token").status_code == 400


def test_email_change_invalidates_reset_links_sent_to_old_address(
    api_client, active_account, django_capture_on_commit_callbacks
):
    services.request_password_reset(email=active_account.email)
    _auth(api_client, active_account.email)
    with django_capture_on_commit_callbacks(execute=True):
        _request_change(api_client, "moved@tara.local")
    _confirm(api_client, _token_from(_mails_to("moved@tara.local")[0]))
    assert not PasswordReset.objects.filter(
        account=active_account, consumed_at__isnull=True
    ).exists()
