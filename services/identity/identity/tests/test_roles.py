"""Roles: Identity is the source of truth, and the token claim follows it."""

import io
import json
import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.urls import reverse

from identity.internal_views import _caller_secret
from identity.models import Account, AccountRole, SecurityEvent
from identity.tokens import issue_access_token
from tara_common.auth import mint_internal_token

pytestmark = pytest.mark.django_db


def _account(email="user@example.com", **extra) -> Account:
    extra.setdefault("email_verified", True)
    extra.setdefault("status", Account.Status.ACTIVE)
    return Account.objects.create_user(email=email, password="Str0ng-Pass-987!", **extra)


def _claims(account: Account) -> dict:
    token, _ = issue_access_token(account, str(uuid.uuid4()))
    return jwt.decode(token, options={"verify_signature": False})


SHARED_SECRET = "shared-internal-secret-every-service-holds-0123456789"
ADMIN_SECRET = "admin-identity-secret-only-admin-holds-0123456789"


@pytest.fixture(autouse=True)
def _distinct_internal_secrets(settings):
    settings.TARA_INTERNAL_JWT_SECRET = SHARED_SECRET
    settings.ADMIN_IDENTITY_SECRET = ADMIN_SECRET


def _internal(audience="identity.roles", secret=None, issuer="admin") -> dict:
    """What admin sends: its own secret, ``iss=admin``, ``aud=identity.roles``."""
    token = mint_internal_token(
        issuer=issuer, audience=audience, secret=secret or settings.ADMIN_IDENTITY_SECRET
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


def _raw(claims: dict, secret: str, algorithm: str = "HS256") -> dict:
    now = int(time.time())
    token = jwt.encode({"iat": now, "exp": now + 30, **claims}, secret, algorithm=algorithm)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


# Built inside the test (not at collection), so no token can expire first and
# pass for the wrong reason.
BAD_TOKENS = {
    "no header": lambda: {},
    "not a jwt": lambda: {"HTTP_AUTHORIZATION": "Bearer nonsense"},
    "not bearer": lambda: {"HTTP_AUTHORIZATION": _internal()["HTTP_AUTHORIZATION"][7:]},
    # The 1.0d blocker: any service holds the shared secret and can claim iss=admin.
    "shared secret, admin claims": lambda: _internal(secret=SHARED_SECRET),
    "shared secret, legacy audience": lambda: _internal(
        audience="identity-internal", secret=SHARED_SECRET
    ),
    "admin secret, wrong issuer": lambda: _internal(issuer="post"),
    "admin secret, another caller": lambda: _internal(issuer="notification"),
    "admin secret, no issuer": lambda: _raw({"aud": "identity.roles"}, ADMIN_SECRET),
    "admin secret, legacy audience": lambda: _internal(audience="identity-internal"),
    "admin secret, other service audience": lambda: _internal(audience="profile-internal"),
    "admin secret, no audience": lambda: _raw({"iss": "admin"}, ADMIN_SECRET),
    "wrong secret": lambda: _internal(secret="wrong-secret-that-is-long-enough-for-hs256"),
    "expired": lambda: _raw(
        {"iss": "admin", "aud": "identity.roles", "iat": 1, "exp": 2}, ADMIN_SECRET
    ),
    "alg none": lambda: _raw({"iss": "admin", "aud": "identity.roles"}, "", algorithm="none"),
    "issuer is a list": lambda: _jws({"iss": ["admin"], "aud": "identity.roles"}, ADMIN_SECRET),
}


def _jws(claims: dict, secret: str) -> dict:
    """Signs claims that jwt.encode would refuse (e.g. a non-string iss)."""
    now = int(time.time())
    payload = json.dumps({"iat": now, "exp": now + 30, **claims}).encode()
    token = jwt.PyJWS().encode(payload, secret, algorithm="HS256")
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def test_a_caller_without_a_mapped_secret_is_never_trusted():
    assert _caller_secret("moderation") is None
    assert _caller_secret("admin") == ADMIN_SECRET


@pytest.mark.parametrize("make_headers", BAD_TOKENS.values(), ids=BAD_TOKENS.keys())
def test_internal_role_api_needs_admins_own_service_token(client, make_headers):
    account = _account()
    headers = make_headers()
    assert client.get(_roles_url(account), **headers).status_code == 401
    body = {"role": "admin", "actor_id": str(uuid.uuid4())}
    resp = client.post(_roles_url(account), body, content_type="application/json", **headers)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthenticated"
    assert not AccountRole.objects.exists()
    assert not SecurityEvent.objects.filter(type="role_granted").exists()


def test_shared_secret_cannot_revoke_or_read_staff(client):
    """Lookup and holders expose emails and roles: they need admin's secret too."""
    staff = _account("staff@example.com", is_staff=True)
    AccountRole.objects.create(account=staff, role="moderator")
    shared = _internal(secret=SHARED_SECRET)

    resp = client.delete(
        _roles_url(staff),
        {"role": "moderator", "actor_id": str(uuid.uuid4())},
        content_type="application/json",
        **shared,
    )
    assert resp.status_code == 401
    assert AccountRole.objects.filter(account=staff, role="moderator").exists()
    lookup = client.get(
        reverse("internal-account-lookup"), {"email": "staff@example.com"}, **shared
    )
    assert lookup.status_code == 401
    assert "staff@example.com" not in lookup.content.decode()
    holders = client.get(reverse("internal-role-holders"), **shared)
    assert holders.status_code == 401
    assert "staff@example.com" not in holders.content.decode()


def test_admin_token_grants(client):
    """Positive control for the matrix above: same request, admin's own token."""
    account = _account()
    resp = client.post(
        _roles_url(account),
        {"role": "admin", "actor_id": str(uuid.uuid4())},
        content_type="application/json",
        **_internal(),
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["roles"] == ["admin"]


def test_unset_admin_secret_fails_closed(client, settings):
    """No fallback to the shared secret when the caller's secret is missing."""
    settings.ADMIN_IDENTITY_SECRET = ""
    account = _account()
    for headers in (_internal(secret=SHARED_SECRET), _internal(secret=ADMIN_SECRET)):
        resp = client.post(
            _roles_url(account),
            {"role": "admin", "actor_id": str(uuid.uuid4())},
            content_type="application/json",
            **headers,
        )
        assert resp.status_code == 401
    assert not AccountRole.objects.exists()


def test_admin_secret_equal_to_shared_secret_fails_closed(client, settings):
    """Misconfigured as the shared secret, it would let every service in."""
    settings.ADMIN_IDENTITY_SECRET = SHARED_SECRET
    account = _account()
    resp = client.post(
        _roles_url(account),
        {"role": "admin", "actor_id": str(uuid.uuid4())},
        content_type="application/json",
        **_internal(secret=SHARED_SECRET),
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
