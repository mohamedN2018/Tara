"""Roles: Identity is the source of truth, and the token claim follows it."""

import io
import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.urls import reverse

from identity.models import Account, AccountRole, SecurityEvent
from identity.tokens import issue_access_token

pytestmark = pytest.mark.django_db


def _account(email="user@example.com", **extra) -> Account:
    extra.setdefault("email_verified", True)
    extra.setdefault("status", Account.Status.ACTIVE)
    return Account.objects.create_user(email=email, password="Str0ng-Pass-987!", **extra)


def _claims(account: Account) -> dict:
    token, _ = issue_access_token(account, str(uuid.uuid4()))
    return jwt.decode(token, options={"verify_signature": False})


def _internal(audience="identity-internal", secret=None) -> dict:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "admin", "aud": audience, "iat": now, "exp": now + 30},
        secret or settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _roles_url(account) -> str:
    return reverse("internal-account-roles", args=[account.id])


@pytest.mark.parametrize("role", ["ad_reviewer", "analyst", "moderator", "admin"])
def test_a_granted_role_reaches_the_token(client, role):
    account = _account()
    assert _claims(account)["roles"] == []
    resp = client.post(
        _roles_url(account),
        {"role": role, "actor_id": str(uuid.uuid4())},
        content_type="application/json",
        **_internal(),
    )
    assert resp.status_code == 201
    assert _claims(account)["roles"] == [role]
    assert SecurityEvent.objects.filter(account=account, type="role_granted").exists()


def test_revoking_removes_the_claim(client):
    account = _account()
    AccountRole.objects.create(account=account, role="analyst")
    resp = client.delete(
        _roles_url(account),
        {"role": "analyst", "actor_id": str(uuid.uuid4())},
        content_type="application/json",
        **_internal(),
    )
    assert resp.status_code == 200
    assert _claims(account)["roles"] == []


def test_staff_and_superuser_bridging_stays(client):
    account = _account(is_staff=True, is_superuser=True)
    AccountRole.objects.create(account=account, role="analyst")
    assert _claims(account)["roles"] == ["admin", "analyst", "moderator"]

    data = client.get(_roles_url(account), **_internal()).json()["data"]
    assert data["bridged_roles"] == ["admin", "moderator"]


def test_duplicate_grant_is_harmless(client):
    account = _account()
    body = {"role": "analyst", "actor_id": str(uuid.uuid4())}
    for _ in range(2):
        client.post(_roles_url(account), body, content_type="application/json", **_internal())
    assert AccountRole.objects.filter(account=account).count() == 1


def test_unknown_role_is_rejected(client):
    resp = client.post(
        _roles_url(_account()),
        {"role": "god", "actor_id": str(uuid.uuid4())},
        content_type="application/json",
        **_internal(),
    )
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"HTTP_AUTHORIZATION": "Bearer nonsense"},
        _internal(audience="profile-internal"),
        _internal(secret="wrong-secret-that-is-long-enough-for-hs256"),
    ],
)
def test_internal_role_api_needs_the_right_service_token(client, headers):
    account = _account()
    assert client.get(_roles_url(account), **headers).status_code == 401
    resp = client.post(
        _roles_url(account),
        {"role": "admin", "actor_id": str(uuid.uuid4())},
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 401
    assert not AccountRole.objects.exists()


def test_lookup_and_holders(client):
    holder = _account("holder@example.com")
    AccountRole.objects.create(account=holder, role="analyst")
    _account("nobody@example.com")
    staff = _account("staff@example.com", is_staff=True)

    data = client.get(
        reverse("internal-account-lookup"), {"email": "HOLDER@example.com"}, **_internal()
    ).json()["data"]
    assert data["account_id"] == str(holder.id)

    assert (
        client.get(
            reverse("internal-account-lookup"), {"email": "x@example.com"}, **_internal()
        ).status_code
        == 404
    )

    holders = client.get(reverse("internal-role-holders"), **_internal()).json()["data"]
    assert {h["email"] for h in holders} == {holder.email, staff.email}


def test_create_admin_promotes_a_verified_account():
    account = _account("boss@example.com")
    out = io.StringIO()
    call_command("create_admin", "BOSS@example.com", stdout=out)
    assert "now an admin" in out.getvalue()
    assert _claims(account)["roles"] == ["admin"]
    call_command("create_admin", "boss@example.com", stdout=out)  # idempotent
    assert AccountRole.objects.filter(account=account).count() == 1


def test_create_admin_refuses_missing_unverified_or_inactive():
    with pytest.raises(CommandError, match="No account"):
        call_command("create_admin", "ghost@example.com")
    _account("new@example.com", email_verified=False)
    with pytest.raises(CommandError, match="verified"):
        call_command("create_admin", "new@example.com")
    _account("banned@example.com", status=Account.Status.SUSPENDED)
    with pytest.raises(CommandError, match="not active"):
        call_command("create_admin", "banned@example.com")
    assert not AccountRole.objects.exists()
