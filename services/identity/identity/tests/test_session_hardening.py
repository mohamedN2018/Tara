"""Review hardening: access tokens die with their session on identity, recovery
artefacts die with the old password, and malformed client input never 500s."""

from __future__ import annotations

import re

import pytest
from django.core import mail
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from identity import services
from identity.models import (
    EmailChangeRequest,
    IdempotencyRecord,
    PasswordReset,
    SecurityEvent,
    UserSession,
)

pytestmark = pytest.mark.django_db

PASSWORD = "DevPassw0rd!"
NEW_PASSWORD = "Fresh-Passw0rd-42"


def _login(email, password=PASSWORD, **extra):
    client = APIClient()
    resp = client.post(
        reverse("identity:login"), {"email": email, "password": password}, format="json", **extra
    )
    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access_token']}")
    return client, data


def _token_from(message) -> str:
    match = re.search(r"token=([\w-]+)", message.body)
    assert match, message.body
    return match.group(1)


# ---- access tokens follow their session on identity -------------------------


def test_password_change_signs_other_sessions_out_of_identity_at_once(active_account):
    mine, _ = _login(active_account.email)
    other, _ = _login(active_account.email)
    assert other.get(reverse("identity:me")).status_code == 200

    resp = mine.post(
        reverse("identity:me-password"),
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert resp.status_code == 200, resp.content

    # The other device's access token has not expired, but its session is gone.
    for url in ("identity:me", "identity:me-security", "identity:session-list"):
        assert other.get(reverse(url)).status_code == 401
    assert (
        other.post(
            reverse("identity:me-email"),
            {"new_email": "thief@tara.local", "password": NEW_PASSWORD},
            format="json",
        ).status_code
        == 401
    )
    assert mine.get(reverse("identity:me")).status_code == 200


def test_logout_ends_the_access_token_on_identity(active_account):
    client, data = _login(active_account.email)
    assert (
        client.post(
            reverse("identity:logout"), {"refresh_token": data["refresh_token"]}, format="json"
        ).status_code
        == 204
    )
    assert client.get(reverse("identity:me")).status_code == 401


def test_revoked_session_token_still_signs_out_and_signs_in(active_account):
    client, data = _login(active_account.email)
    UserSession.objects.update(revoked_at=timezone.now())

    # Logout and login must not trip over the dead access token the client still sends.
    assert (
        client.post(
            reverse("identity:logout"), {"refresh_token": data["refresh_token"]}, format="json"
        ).status_code
        == 204
    )
    resp = client.post(
        reverse("identity:login"),
        {"email": active_account.email, "password": PASSWORD},
        format="json",
    )
    assert resp.status_code == 200, resp.content


@pytest.mark.parametrize("header", ["Bearer not-a-jwt", "Bearer a.b.c", "   "])
def test_public_auth_endpoints_ignore_a_bad_bearer(api_client, active_account, header):
    api_client.credentials(HTTP_AUTHORIZATION=header)
    resp = api_client.post(
        reverse("identity:login"),
        {"email": active_account.email, "password": PASSWORD},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    forgot = api_client.post(
        reverse("identity:password-forgot"), {"email": active_account.email}, format="json"
    )
    assert forgot.status_code == 202


def test_blank_authorization_header_is_unauthenticated_not_500(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="   ")
    assert api_client.get(reverse("identity:me")).status_code == 401


def test_token_without_a_session_id_is_rejected(active_account):
    from identity.tokens import issue_access_token

    token, _ = issue_access_token(active_account, "not-a-uuid")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert client.get(reverse("identity:me")).status_code == 401


# ---- recovery artefacts die with the old password ---------------------------


def _pending_email_change(client, new_email, django_capture_on_commit_callbacks, password):
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(
            reverse("identity:me-email"),
            {"new_email": new_email, "password": password},
            format="json",
        )
    assert resp.status_code == 202, resp.content
    return _token_from([m for m in mail.outbox if new_email in m.to][-1])


def _confirm(token):
    return APIClient().post(
        reverse("identity:email-change-confirm"), {"token": token}, format="json"
    )


def test_password_reset_cancels_an_email_change_started_with_the_old_password(
    active_account, django_capture_on_commit_callbacks
):
    # Someone who learnt the password moves the account to their own inbox...
    thief, _ = _login(active_account.email)
    link = _pending_email_change(
        thief, "thief@tara.local", django_capture_on_commit_callbacks, PASSWORD
    )
    # ...the owner resets the password...
    with django_capture_on_commit_callbacks(execute=True):
        services.request_password_reset(email=active_account.email)
        services.request_password_reset(email=active_account.email)
    reset_mails = [
        m for m in mail.outbox if active_account.email in m.to and "reset" in m.subject.lower()
    ]
    used, spare = _token_from(reset_mails[-1]), _token_from(reset_mails[-2])
    resp = APIClient().post(
        reverse("identity:password-reset"), {"token": used, "password": NEW_PASSWORD}, format="json"
    )
    assert resp.status_code == 200, resp.content

    # ...and neither the thief's link nor the other reset link works any more.
    assert _confirm(link).status_code == 400
    active_account.refresh_from_db()
    assert active_account.email == "active@tara.local"
    assert not EmailChangeRequest.objects.filter(cancelled_at__isnull=True).exists()
    assert not PasswordReset.objects.filter(consumed_at__isnull=True).exists()
    again = APIClient().post(
        reverse("identity:password-reset"),
        {"token": spare, "password": "Another-Passw0rd-7"},
        format="json",
    )
    assert again.status_code == 400


def test_password_change_cancels_a_pending_email_change(
    active_account, django_capture_on_commit_callbacks
):
    client, _ = _login(active_account.email)
    link = _pending_email_change(
        client, "elsewhere@tara.local", django_capture_on_commit_callbacks, PASSWORD
    )
    resp = client.post(
        reverse("identity:me-password"),
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert resp.status_code == 200
    assert _confirm(link).status_code == 400


# ---- input that used to 500 -------------------------------------------------


def test_oversized_request_id_is_replaced_not_stored(active_account):
    client = APIClient()
    resp = client.post(
        reverse("identity:login"),
        {"email": active_account.email, "password": PASSWORD},
        format="json",
        HTTP_X_REQUEST_ID="x" * 500,
    )
    assert resp.status_code == 200, resp.content
    assert resp["X-Request-Id"].startswith("req_")

    kept = client.get("/healthz/", HTTP_X_REQUEST_ID="ok-1")
    assert kept["X-Request-Id"] == "ok-1"


def test_jwks_outage_is_503_not_401(api_client, active_account, settings):
    settings.TARA_JWT_PUBLIC_KEY = ""
    settings.TARA_JWKS_URL = "http://127.0.0.1:9/.well-known/jwks.json"
    settings.TARA_JWKS_TIMEOUT = 1
    from identity.tokens import issue_access_token

    token, _ = issue_access_token(active_account, "0190d6a1-0000-7000-8000-000000000000")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    resp = api_client.get(reverse("identity:me"))
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "dependency_unavailable"


def test_idempotency_key_released_mid_race_is_a_conflict_not_500(api_client, monkeypatch):
    def lost_race(**_kwargs):
        raise IntegrityError("duplicate key")

    monkeypatch.setattr(IdempotencyRecord.objects, "create", lost_race)
    resp = api_client.post(
        reverse("identity:register"),
        {"email": "race@tara.local", "password": PASSWORD},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k-1",
    )
    assert resp.status_code == 409


# ---- smaller fixes ----------------------------------------------------------


def test_registration_security_event_does_not_keep_the_email(api_client):
    resp = api_client.post(
        reverse("identity:register"),
        {"email": "private@tara.local", "password": PASSWORD},
        format="json",
    )
    assert resp.status_code == 201
    event = SecurityEvent.objects.get(type="account_registered")
    assert "private@tara.local" not in str(event.metadata)


@pytest.mark.parametrize("field,value", [("theme", "neon"), ("language", "xx")])
def test_me_rejects_unknown_language_or_theme(active_account, field, value):
    client, _ = _login(active_account.email)
    resp = client.patch(reverse("identity:me"), {field: value}, format="json")
    assert resp.status_code == 400
    ok = client.patch(reverse("identity:me"), {"theme": "dark", "language": "ar"}, format="json")
    assert ok.status_code == 200
    assert ok.json()["data"]["theme"] == "dark"


def test_duplicate_device_rows_do_not_break_login(active_account):
    from identity.models import Device

    for _ in range(2):  # what two concurrent first logins leave behind
        Device.objects.create(account=active_account, platform="web", label="same-agent")
    _login(active_account.email, HTTP_USER_AGENT="same-agent")


def test_session_list_leaves_out_sessions_that_can_no_longer_refresh(active_account, settings):
    from datetime import timedelta

    client, _ = _login(active_account.email)
    _login(active_account.email)
    stale = UserSession.objects.order_by("created_at").last()  # the other device
    UserSession.objects.filter(id=stale.id).update(
        last_seen_at=timezone.now() - timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS + 60)
    )
    listed = client.get(reverse("identity:session-list")).json()["data"]
    assert [s["id"] for s in listed] == [
        str(s.id) for s in UserSession.objects.exclude(id=stale.id)
    ]


@pytest.mark.parametrize("handle", ["admin", "Tara", "LOOKUP"])
def test_register_rejects_a_handle_profile_reserves(api_client, handle):
    resp = api_client.post(
        reverse("identity:register"),
        {"email": "h@tara.local", "password": PASSWORD, "handle": handle},
        format="json",
    )
    assert resp.status_code == 400
    detail = resp.json()["error"]["details"][0]
    assert (detail["field"], detail["code"]) == ("handle", "reserved_handle")


def test_account_events_carry_no_email_address(api_client, django_capture_on_commit_callbacks):
    from identity.models import OutboxEvent

    with django_capture_on_commit_callbacks(execute=True):
        api_client.post(
            reverse("identity:register"),
            {"email": "bus@tara.local", "password": PASSWORD, "handle": "bus_rider"},
            format="json",
        )
    verified = api_client.post(
        reverse("identity:verify-email"), {"token": _token_from(mail.outbox[-1])}, format="json"
    )
    assert verified.status_code == 200
    events = {e.event_type: e.payload for e in OutboxEvent.objects.all()}
    assert events["account.registered"]["payload"]["handle"] == "bus_rider"
    for event_type in ("account.registered", "account.verified"):
        assert "bus@tara.local" not in str(events[event_type])


# ---- stale idempotency claims -----------------------------------------------


def _claim_left_by_a_crash(data: dict, key: str, *, age_seconds: int) -> None:
    """The row a request leaves when its process dies before finishing."""
    from datetime import timedelta
    from types import SimpleNamespace

    from tara_resilience.idempotency import _fingerprint, _scoped_key

    request = SimpleNamespace(
        user=None, data=data, method="POST", path=reverse("identity:register")
    )
    row = IdempotencyRecord.objects.create(
        key=_scoped_key(request, key),
        fingerprint=_fingerprint(request),
        expires_at=timezone.now() + timedelta(days=1),
    )
    IdempotencyRecord.objects.filter(id=row.id).update(
        created_at=timezone.now() - timedelta(seconds=age_seconds)
    )


def test_retry_takes_over_a_claim_left_by_a_crashed_request(api_client):
    data = {"email": "crash@tara.local", "password": PASSWORD}
    _claim_left_by_a_crash(data, "k-crash", age_seconds=120)
    resp = api_client.post(
        reverse("identity:register"), data, format="json", HTTP_IDEMPOTENCY_KEY="k-crash"
    )
    assert resp.status_code == 201, resp.content
    record = IdempotencyRecord.objects.get()
    assert record.in_progress is False and record.response_status == 201
    # The replay now returns the stored response.
    again = api_client.post(
        reverse("identity:register"), data, format="json", HTTP_IDEMPOTENCY_KEY="k-crash"
    )
    assert again.status_code == 201
    assert again.json() == resp.json()


def test_a_recent_claim_is_still_in_progress(api_client, settings):
    settings.TARA_IDEMPOTENCY_STALE_SECONDS = 300
    data = {"email": "slow@tara.local", "password": PASSWORD}
    _claim_left_by_a_crash(data, "k-slow", age_seconds=120)
    resp = api_client.post(
        reverse("identity:register"), data, format="json", HTTP_IDEMPOTENCY_KEY="k-slow"
    )
    assert resp.status_code == 409
    from identity.models import Account

    assert not Account.objects.filter(email="slow@tara.local").exists()


# ---- metrics ----------------------------------------------------------------


def test_outbox_relay_counts_published_events(api_client):
    from prometheus_client import REGISTRY

    from identity.models import OutboxEvent
    from tara_events.outbox import publish_pending
    from tara_events.publisher import NullPublisher

    labels = {"event_type": "account.registered", "service": "identity"}
    before = REGISTRY.get_sample_value("tara_events_published_total", labels) or 0
    api_client.post(
        reverse("identity:register"),
        {"email": "metric@tara.local", "password": PASSWORD},
        format="json",
    )
    assert OutboxEvent.objects.filter(event_type="account.registered").exists()
    assert publish_pending(OutboxEvent, publisher=NullPublisher()) >= 1
    assert REGISTRY.get_sample_value("tara_events_published_total", labels) == before + 1
