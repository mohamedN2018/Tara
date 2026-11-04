"""API-level tests for the Identity auth flows + uniform error/permission shape.

Covers Phase-1 slices of the brief's critical E2E flow #1 (register → verify →
login) and the security requirement that unauthorized users are rejected.
"""

import hashlib

import pytest
from django.urls import reverse
from django.utils import timezone

from identity.models import Account, EmailVerification, OutboxEvent, UserSession
from identity.tests.signup import signup_data

pytestmark = pytest.mark.django_db


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---- register ---------------------------------------------------------------


def test_register_creates_pending_account_and_outbox_event(api_client):
    resp = api_client.post(
        reverse("identity:register"),
        signup_data("new@tara.local", "DevPassw0rd!"),
        format="json",
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["email"] == "new@tara.local"
    assert body["status"] == Account.Status.PENDING

    account = Account.objects.get(email="new@tara.local")
    assert account.email_verified is False
    # Outbox event staged for the rest of the platform.
    assert OutboxEvent.objects.filter(event_type="account.registered", id__isnull=False).exists()


def test_register_rejects_weak_password_with_uniform_error(api_client):
    resp = api_client.post(
        reverse("identity:register"),
        signup_data("weak@tara.local", "123"),
        format="json",
    )
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert "request_id" in err


def test_register_duplicate_email_conflicts(api_client):
    payload = signup_data("dupe@tara.local", "DevPassw0rd!")
    assert api_client.post(reverse("identity:register"), payload, format="json").status_code == 201
    resp = api_client.post(reverse("identity:register"), payload, format="json")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


# ---- login ------------------------------------------------------------------


def test_login_blocked_until_account_active(api_client):
    api_client.post(
        reverse("identity:register"),
        signup_data("pending@tara.local", "DevPassw0rd!"),
        format="json",
    )
    resp = api_client.post(
        reverse("identity:login"),
        {"email": "pending@tara.local", "password": "DevPassw0rd!"},
        format="json",
    )
    assert resp.status_code == 403


def test_login_success_returns_tokens_and_sets_cookie(api_client, active_account):
    resp = api_client.post(
        reverse("identity:login"),
        {"email": active_account.email, "password": "DevPassw0rd!"},
        format="json",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["token_type"] == "Bearer"
    assert data["access_token"] and data["refresh_token"]
    assert "refresh_token" in resp.cookies  # httpOnly cookie for web


def test_login_wrong_password_is_401(api_client, active_account):
    resp = api_client.post(
        reverse("identity:login"),
        {"email": active_account.email, "password": "WrongPassw0rd!"},
        format="json",
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "authentication_failed"


# ---- access token protects endpoints ----------------------------------------


def test_me_requires_authentication(api_client):
    resp = api_client.get(reverse("identity:me"))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] in ("unauthenticated", "authentication_failed")


def test_access_token_authenticates_me(api_client, active_account):
    login = api_client.post(
        reverse("identity:login"),
        {"email": active_account.email, "password": "DevPassw0rd!"},
        format="json",
    ).json()["data"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login['access_token']}")
    resp = api_client.get(reverse("identity:me"))
    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == active_account.email


# ---- refresh rotation + reuse detection -------------------------------------


def test_refresh_rotates_and_detects_reuse(api_client, active_account, settings):
    settings.REFRESH_REUSE_GRACE_SECONDS = 0  # the grace window has its own tests
    login = api_client.post(
        reverse("identity:login"),
        {"email": active_account.email, "password": "DevPassw0rd!"},
        format="json",
    ).json()["data"]
    first_refresh = login["refresh_token"]

    # First rotation succeeds and returns a new refresh token.
    ok = api_client.post(
        reverse("identity:refresh"), {"refresh_token": first_refresh}, format="json"
    )
    assert ok.status_code == 200
    rotated = ok.json()["data"]["refresh_token"]
    assert rotated != first_refresh

    # Replaying the now-spent first token is detected as reuse -> 401.
    reuse = api_client.post(
        reverse("identity:refresh"), {"refresh_token": first_refresh}, format="json"
    )
    assert reuse.status_code == 401

    # The whole family + session are revoked, so even the rotated token is dead.
    after = api_client.post(reverse("identity:refresh"), {"refresh_token": rotated}, format="json")
    assert after.status_code == 401
    assert UserSession.objects.filter(account=active_account, revoked_at__isnull=False).exists()


# ---- email verification ------------------------------------------------------


def test_verify_email_activates_account(api_client):
    account = Account.objects.create_user(
        email="verify@tara.local", password="DevPassw0rd!", status=Account.Status.PENDING
    )
    raw = "known-verification-token"
    EmailVerification.objects.create(
        account=account,
        token_hash=_hash(raw),
        expires_at=timezone.now() + timezone.timedelta(hours=1),
    )
    resp = api_client.post(reverse("identity:verify-email"), {"token": raw}, format="json")
    assert resp.status_code == 200
    account.refresh_from_db()
    assert account.email_verified is True
    assert account.status == Account.Status.ACTIVE


# ---- jwks --------------------------------------------------------------------


def test_jwks_exposes_public_key(api_client, settings):
    resp = api_client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["kid"] == settings.JWT_KEY_ID
    assert keys[0]["alg"] == "RS256"


# ---- sessions ----------------------------------------------------------------


def test_session_list_and_revoke(api_client, active_account):
    login = api_client.post(
        reverse("identity:login"),
        {"email": active_account.email, "password": "DevPassw0rd!"},
        format="json",
    ).json()["data"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login['access_token']}")

    listing = api_client.get(reverse("identity:session-list"))
    assert listing.status_code == 200
    sessions = listing.json()["data"]
    assert len(sessions) == 1
    assert sessions[0]["is_current"] is True

    session_id = sessions[0]["id"]
    revoke = api_client.delete(reverse("identity:session-delete", args=[session_id]))
    assert revoke.status_code == 204
    # Refresh token tied to the revoked session must now fail.
    assert (
        api_client.post(
            reverse("identity:refresh"), {"refresh_token": login["refresh_token"]}, format="json"
        ).status_code
        == 401
    )
