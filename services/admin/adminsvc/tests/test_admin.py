"""Admin: feature flags, and role management through Identity."""

import uuid

import jwt
import pytest
import requests
from django.urls import reverse

from adminsvc import identity_client
from adminsvc.models import AuditLog, FeatureFlag
from tara_common.exceptions import TaraAPIError

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def test_flag_read_open_write_admin_only(client_for):
    key = "new_feed_ranking"
    # Any authenticated user can read flags (to gate features).
    assert (
        client_for(_acct()).get(reverse("adminsvc:feature-flag-detail", args=[key])).status_code
        == 200
    )
    # Non-admin cannot set.
    forbidden = client_for(_acct()).patch(
        reverse("adminsvc:feature-flag-detail", args=[key]), {"enabled": True}, format="json"
    )
    assert forbidden.status_code == 403
    # Admin can set.
    ok = client_for(_acct(), roles=["admin"]).patch(
        reverse("adminsvc:feature-flag-detail", args=[key]),
        {"enabled": True, "rollout_pct": 50},
        format="json",
    )
    assert ok.status_code == 200
    assert FeatureFlag.objects.get(key=key).enabled is True


class FakeIdentity:
    """Stands in for Identity's internal API, which owns the roles."""

    def __init__(self):
        self.roles: dict[str, set] = {}
        self.bridged: dict[str, list] = {}

    def _account(self, account_id):
        account_id = str(account_id)
        return {
            "account_id": account_id,
            "email": "a@example.com",
            "roles": sorted(self.roles.get(account_id, set())),
            "bridged_roles": self.bridged.get(account_id, []),
        }

    def account_roles(self, account_id):
        return self._account(account_id)

    def lookup(self, email):
        if email == "missing@example.com":
            raise TaraAPIError("Account not found.", code="not_found", http_status_code=404)
        return self._account("00000000-0000-0000-0000-000000000001")

    def role_holders(self):
        return [self._account(a) for a in self.roles]

    def grant(self, account_id, role, actor_id):
        self.roles.setdefault(str(account_id), set()).add(role)
        return self._account(account_id)

    def revoke(self, account_id, role, actor_id):
        self.roles.get(str(account_id), set()).discard(role)
        return self._account(account_id)


@pytest.fixture
def identity(monkeypatch):
    fake = FakeIdentity()
    for name in ("account_roles", "lookup", "role_holders", "grant", "revoke"):
        monkeypatch.setattr(f"adminsvc.identity_client.{name}", getattr(fake, name))
    return fake


@pytest.mark.parametrize("role", ["moderator", "ad_reviewer", "analyst", "admin"])
def test_role_grant_and_revoke_go_through_identity_and_are_audited(client_for, identity, role):
    target = _acct()
    admin = client_for(_acct(), roles=["admin"])
    url = reverse("adminsvc:roles")
    body = {"account_id": target, "role": role}
    assert admin.post(url, body, format="json").status_code == 201
    assert role in identity.roles[target]
    assert (
        role in admin.get(reverse("adminsvc:account-roles", args=[target])).json()["data"]["roles"]
    )
    assert admin.get(url).json()["data"][0]["account_id"] == target

    assert admin.delete(url, body, format="json").status_code == 200
    assert role not in identity.roles[target]
    actions = set(AuditLog.objects.filter(target=target).values_list("action", flat=True))
    assert actions == {"role.grant", "role.revoke"}


def test_retired_roles_are_rejected(client_for, identity):
    resp = client_for(_acct(), roles=["admin"]).post(
        reverse("adminsvc:roles"), {"account_id": _acct(), "role": "editor"}, format="json"
    )
    assert resp.status_code == 400


def test_non_admin_cannot_manage_roles(client_for, identity):
    moderator = client_for(_acct(), roles=["moderator"])
    url = reverse("adminsvc:roles")
    assert (
        moderator.post(url, {"account_id": _acct(), "role": "admin"}, format="json").status_code
        == 403
    )
    assert moderator.get(url).status_code == 403
    assert moderator.get(reverse("adminsvc:role-lookup"), {"email": "a@b.c"}).status_code == 403
    assert not identity.roles


def test_lookup_by_email(client_for, identity):
    admin = client_for(_acct(), roles=["admin"])
    url = reverse("adminsvc:role-lookup")
    assert admin.get(url).status_code == 400
    assert admin.get(url, {"email": "found@example.com"}).status_code == 200
    assert admin.get(url, {"email": "missing@example.com"}).status_code == 404


def test_admin_cannot_remove_their_own_admin_role(client_for, identity):
    me = _acct()
    identity.roles[me] = {"admin"}
    resp = client_for(me, roles=["admin"]).delete(
        reverse("adminsvc:roles"), {"account_id": me, "role": "admin"}, format="json"
    )
    assert resp.status_code == 400
    assert "admin" in identity.roles[me]


def test_bridged_role_cannot_be_revoked_here(client_for, identity):
    target = _acct()
    identity.bridged[target] = ["moderator"]
    resp = client_for(_acct(), roles=["admin"]).delete(
        reverse("adminsvc:roles"), {"account_id": target, "role": "moderator"}, format="json"
    )
    assert resp.status_code == 409


def test_identity_outage_is_reported_not_swallowed(client_for, monkeypatch):
    def down(*args, **kwargs):
        raise requests.ConnectionError

    monkeypatch.setattr("adminsvc.identity_client.requests.request", down)
    resp = client_for(_acct(), roles=["admin"]).post(
        reverse("adminsvc:roles"), {"account_id": _acct(), "role": "analyst"}, format="json"
    )
    assert resp.status_code == 503
    assert not AuditLog.objects.exists()


def test_identity_client_sends_a_service_token(monkeypatch, settings):
    captured = {}

    def fake(method, url, **kwargs):
        captured.update(kwargs, method=method, url=url)
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"data": {"roles": []}}'
        return response

    monkeypatch.setattr("adminsvc.identity_client.requests.request", fake)
    account = _acct()
    identity_client.grant(account, "analyst", _acct())
    assert captured["url"].endswith(f"/internal/v1/accounts/{account}/roles/")
    token = captured["headers"]["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(
        token,
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithms=["HS256"],
        audience="identity-internal",
    )
    assert claims["iss"] == "admin"
