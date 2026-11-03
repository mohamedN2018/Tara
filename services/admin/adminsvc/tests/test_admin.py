"""Admin: feature flags, and role management through Identity."""

import uuid

import jwt
import pytest
import requests
from django.test import override_settings
from django.urls import reverse

from adminsvc import identity_client
from adminsvc.models import AuditLog, FeatureFlag
from tara_common.checks import production_safety_check
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


SHARED_SECRET = "shared-internal-secret-every-service-holds-0123456789"
ADMIN_SECRET = "admin-identity-secret-only-admin-holds-0123456789"


def _fake_identity(monkeypatch, status=200, body=b'{"data": {"roles": []}}'):
    captured = {"calls": 0}

    def fake(method, url, **kwargs):
        captured.update(kwargs, method=method, url=url)
        captured["calls"] += 1
        response = requests.Response()
        response.status_code = status
        response._content = body
        return response

    monkeypatch.setattr("adminsvc.identity_client.requests.request", fake)
    return captured


def test_identity_client_signs_with_the_admin_only_secret(monkeypatch, settings):
    settings.TARA_INTERNAL_JWT_SECRET = SHARED_SECRET
    settings.ADMIN_IDENTITY_SECRET = ADMIN_SECRET
    captured = _fake_identity(monkeypatch)
    account = _acct()
    identity_client.grant(account, "analyst", _acct())
    assert captured["url"].endswith(f"/internal/v1/accounts/{account}/roles/")
    assert captured["timeout"] == settings.IDENTITY_CALL_TIMEOUT
    token = captured["headers"]["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(
        token,
        ADMIN_SECRET,
        algorithms=["HS256"],
        audience="identity.roles",
        issuer="admin",
        options={"require": ["exp", "iat", "iss", "aud"]},
    )
    assert claims["exp"] - claims["iat"] <= 30
    # Not signed with the secret every service holds.
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, SHARED_SECRET, algorithms=["HS256"], audience="identity.roles")


def test_identity_client_refuses_to_call_without_its_secret(client_for, monkeypatch, settings):
    settings.ADMIN_IDENTITY_SECRET = ""
    captured = _fake_identity(monkeypatch)
    resp = client_for(_acct(), roles=["admin"]).post(
        reverse("adminsvc:roles"), {"account_id": _acct(), "role": "analyst"}, format="json"
    )
    assert resp.status_code == 503
    assert captured["calls"] == 0  # never falls back to the shared secret
    assert not AuditLog.objects.exists()


@pytest.mark.parametrize("status", [401, 403])
def test_identity_refusing_the_service_token_is_a_503(client_for, monkeypatch, status):
    _fake_identity(monkeypatch, status=status, body=b'{"error": {"code": "unauthenticated"}}')
    resp = client_for(_acct(), roles=["admin"]).post(
        reverse("adminsvc:roles"), {"account_id": _acct(), "role": "analyst"}, format="json"
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "dependency_unavailable"
    assert not AuditLog.objects.exists()


def test_admin_deploy_check_requires_the_admin_identity_secret(settings):
    assert hasattr(settings, "ADMIN_IDENTITY_SECRET")
    with override_settings(
        DEBUG=False, ADMIN_IDENTITY_SECRET="dev-only-admin-identity-secret-change-me"
    ):
        ids = {m.id for m in production_safety_check() if m.is_serious()}
    assert "tara.E007" in ids


def test_overlong_flag_key_is_a_400_not_a_500(client_for):
    resp = client_for(_acct(), roles=["admin"]).patch(
        reverse("adminsvc:feature-flag-detail", args=["k" * 81]), {"enabled": True}, format="json"
    )
    assert resp.status_code == 400
    assert not FeatureFlag.objects.exists()


def test_half_open_breaker_lets_one_probe_through_at_a_time():
    from tara_resilience import CircuitBreaker, CircuitOpenError

    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=lambda: now[0])
    with pytest.raises(ZeroDivisionError):
        breaker.call(lambda: 1 / 0)
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "too soon")

    now[0] = 11.0
    seen = []

    def probe():
        # A second caller arriving while the probe is still out is turned away.
        with pytest.raises(CircuitOpenError):
            breaker.call(lambda: "concurrent")
        seen.append("probe")
        return "ok"

    assert breaker.call(probe) == "ok"
    assert seen == ["probe"]
    assert breaker.state == "closed"
    assert breaker.call(lambda: "after") == "after"


def test_health_poll_keeps_only_the_newest_snapshots(client_for, monkeypatch, settings):
    from adminsvc.models import ServiceHealthSnapshot

    settings.HEALTH_TARGETS = {"identity": "http://identity:8000/readyz/"}
    settings.HEALTH_SNAPSHOTS_KEPT = 3

    def down(*args, **kwargs):
        raise requests.ConnectionError

    monkeypatch.setattr("adminsvc.services.requests.get", down)
    from datetime import timedelta

    from django.utils import timezone

    for minutes in range(5):  # distinct ages, oldest last
        row = ServiceHealthSnapshot.objects.create(service="identity", status="ready")
        ServiceHealthSnapshot.objects.filter(id=row.id).update(
            checked_at=timezone.now() - timedelta(minutes=minutes + 1)
        )
    newest_before = set(
        ServiceHealthSnapshot.objects.order_by("-checked_at").values_list("id", flat=True)[:2]
    )
    resp = client_for(_acct(), roles=["admin"]).get(reverse("adminsvc:service-health"))
    assert resp.status_code == 200
    kept = ServiceHealthSnapshot.objects.filter(service="identity")
    assert kept.count() == 3
    assert kept.filter(status="unreachable").count() == 1  # this poll's row survives
    assert newest_before <= set(kept.values_list("id", flat=True))
