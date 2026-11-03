"""Capabilities (8.12): the shared registry, the ``caps`` claim and the matrix API.

``tara_common`` has no suite of its own, so its registry and ``HasCapability``
are tested here, next to the token that carries the claim.
"""

import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIRequestFactory

from identity.models import Account, AccountRole, OutboxEvent, RoleCapability
from identity.tokens import issue_access_token
from tara_common import capabilities as registry
from tara_common.auth import TokenUser, mint_internal_token
from tara_common.permissions import HasCapability

pytestmark = pytest.mark.django_db

SHARED_SECRET = "shared-internal-secret-every-service-holds-0123456789"
ADMIN_SECRET = "admin-identity-secret-only-admin-holds-0123456789"
MODERATION = {
    "moderation.case.view",
    "moderation.case.act",
    "moderation.appeal.view",
    "moderation.appeal.resolve",
}


@pytest.fixture(autouse=True)
def _distinct_internal_secrets(settings):
    settings.TARA_INTERNAL_JWT_SECRET = SHARED_SECRET
    settings.ADMIN_IDENTITY_SECRET = ADMIN_SECRET


def _account(email="caps@example.com", **extra) -> Account:
    extra.setdefault("email_verified", True)
    extra.setdefault("status", Account.Status.ACTIVE)
    return Account.objects.create_user(email=email, password="Str0ng-Pass-987!", **extra)


def _claims(account: Account) -> dict:
    token, _ = issue_access_token(account, str(uuid.uuid4()))
    return jwt.decode(token, options={"verify_signature": False})


def _admin_call(audience="identity.roles") -> dict:
    token = mint_internal_token(issuer="admin", audience=audience, secret=ADMIN_SECRET)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


# ---- registry ---------------------------------------------------------------


def test_default_map_matches_the_role_checks_it_replaces():
    assert registry.capabilities_for_roles(["admin"]) == frozenset(registry.CAPABILITIES)
    assert registry.capabilities_for_roles(["moderator"]) == MODERATION
    assert registry.capabilities_for_roles(["ad_reviewer"]) == {"ads.review"}
    assert registry.capabilities_for_roles(["analyst"]) == frozenset()
    assert registry.capabilities_for_roles([]) == frozenset()
    assert registry.capabilities_for_roles(["unknown-role"]) == frozenset()


def test_keys_are_namespaced():
    for cap in registry.CAPABILITIES.values():
        assert cap.namespace in {"moderation", "ads", "admin"}
        assert cap.key.count(".") >= 1


def test_overrides_then_implies():
    grant = {("analyst", "admin.audit.export"): True}
    assert registry.role_capabilities("analyst", grant) == {
        "admin.audit.export",
        "admin.audit.view",
    }
    revoke = {("moderator", "moderation.case.view"): False}
    # Acting on a case means seeing it: the implied view comes back.
    assert "moderation.case.view" in registry.role_capabilities("moderator", revoke)
    revoke_act = {("moderator", "moderation.case.act"): False}
    assert "moderation.case.act" not in registry.role_capabilities("moderator", revoke_act)


def test_the_locked_admin_role_ignores_overrides():
    revoke = {("admin", "admin.capabilities.manage"): False}
    assert registry.role_capabilities("admin", revoke) == frozenset(registry.CAPABILITIES)


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"roles": ["moderator"]}, MODERATION),  # minted before caps existed
        ({"roles": ["moderator"], "caps": ["ads.review"]}, {"ads.review"}),  # caps win
        ({"roles": ["admin"], "caps": []}, frozenset()),
        ({}, frozenset()),
        ({"roles": "admin"}, frozenset()),  # malformed claim, not a crash
        ({"caps": ["ads.review", 7, None]}, {"ads.review"}),
    ],
)
def test_capabilities_from_claims(claims, expected):
    assert registry.capabilities_from_claims(claims) == expected


def _request_with(claims: dict):
    request = APIRequestFactory().get("/")
    request.user = TokenUser({"sub": str(uuid.uuid4()), **claims})
    return request


def test_has_capability_checks_the_token():
    act = HasCapability("moderation.case.act")
    assert act().has_permission(_request_with({"roles": ["moderator"]}), None)
    assert act().has_permission(_request_with({"caps": ["moderation.case.act"]}), None)
    assert not act().has_permission(_request_with({"roles": ["ad_reviewer"]}), None)
    assert not act().has_permission(_request_with({"roles": ["moderator"], "caps": []}), None)
    both = HasCapability("admin.audit.view", "admin.audit.export")
    assert not both.has_permission(_request_with({"caps": ["admin.audit.view"]}), None)


def test_has_capability_refuses_unknown_keys():
    with pytest.raises(ValueError):
        HasCapability("moderation.cases.view")


# ---- the caps claim -----------------------------------------------------------


def test_access_tokens_carry_sorted_caps_and_no_email():
    account = _account()
    AccountRole.objects.create(account=account, role="moderator")
    claims = _claims(account)
    assert "email" not in claims
    assert claims["roles"] == ["moderator"]
    assert claims["caps"] == sorted(MODERATION)


def test_an_ordinary_member_has_empty_caps():
    claims = _claims(_account())
    assert claims["caps"] == [] and claims["roles"] == []


def test_matrix_overrides_reach_the_token():
    account = _account()
    AccountRole.objects.create(account=account, role="analyst")
    assert _claims(account)["caps"] == []
    RoleCapability.objects.create(role="analyst", capability="admin.monitor.view", granted=True)
    assert _claims(account)["caps"] == ["admin.monitor.view"]


def test_superuser_bridging_still_gives_every_capability():
    account = _account(is_superuser=True)
    assert set(_claims(account)["caps"]) == set(registry.CAPABILITIES)


# ---- internal matrix API ----------------------------------------------------


URL = "internal-capabilities"


def _put(client, changes, actor=None, **headers):
    return client.put(
        reverse(URL),
        {"changes": changes, "actor_id": actor or str(uuid.uuid4())},
        content_type="application/json",
        **_admin_call(),
        **headers,
    )


def test_matrix_get_describes_the_registry(client):
    data = client.get(reverse(URL), **_admin_call()).json()["data"]
    assert [c["key"] for c in data["capabilities"]] == list(registry.CAPABILITIES)
    assert data["roles"] == list(registry.ROLES)
    assert data["locked_roles"] == ["admin"]
    assert data["defaults"]["moderator"] == sorted(MODERATION)
    assert data["effective"]["admin"] == sorted(registry.CAPABILITIES)
    assert data["implies"]["admin.audit.export"] == ["admin.audit.view"]


def test_a_matrix_change_is_stored_and_emits_one_event(client):
    actor = str(uuid.uuid4())
    change = {"role": "analyst", "capability": "admin.monitor.view", "state": "grant"}
    resp = _put(client, [change], actor=actor, HTTP_X_REQUEST_ID="edge-req-1")
    assert resp.status_code == 200
    assert resp.json()["data"]["effective"]["analyst"] == ["admin.monitor.view"]
    row = RoleCapability.objects.get(role="analyst", capability="admin.monitor.view")
    assert row.granted and str(row.updated_by) == actor
    event = OutboxEvent.objects.get(event_type="capability.matrix.changed")
    assert event.payload["payload"] == {
        "role": "analyst",
        "capability": "admin.monitor.view",
        "state": "grant",
        "previous": "default",
    }
    assert event.payload["actor_id"] == actor
    assert event.correlation_id == "edge-req-1"

    # The same batch again changes nothing and emits nothing.
    assert _put(client, [change]).status_code == 200
    assert OutboxEvent.objects.filter(event_type="capability.matrix.changed").count() == 1


def test_resetting_to_default_removes_the_override(client):
    RoleCapability.objects.create(role="moderator", capability="moderation.case.act", granted=False)
    resp = _put(
        client, [{"role": "moderator", "capability": "moderation.case.act", "state": "default"}]
    )
    assert resp.status_code == 200
    assert not RoleCapability.objects.exists()
    event = OutboxEvent.objects.get(event_type="capability.matrix.changed")
    assert event.payload["payload"]["previous"] == "revoke"
    # Resetting a cell that has no override is a harmless no-op.
    again = _put(
        client, [{"role": "moderator", "capability": "moderation.case.act", "state": "default"}]
    )
    assert again.status_code == 200


@pytest.mark.parametrize(
    "change",
    [
        {"role": "admin", "capability": "admin.capabilities.manage", "state": "revoke"},
        {"role": "analyst", "capability": "admin.everything", "state": "grant"},
        {"role": "god", "capability": "ads.review", "state": "grant"},
        {"role": "analyst", "capability": "ads.review", "state": "maybe"},
    ],
)
def test_invalid_matrix_changes_are_400(client, change):
    assert _put(client, [change]).status_code == 400
    assert not RoleCapability.objects.exists()
    assert not OutboxEvent.objects.filter(event_type="capability.matrix.changed").exists()


def test_duplicate_cells_in_one_batch_are_400(client):
    change = {"role": "analyst", "capability": "ads.review", "state": "grant"}
    assert _put(client, [change, {**change, "state": "revoke"}]).status_code == 400


def test_matrix_refuses_the_shared_secret(client):
    token = mint_internal_token(issuer="admin", audience="identity.roles", secret=SHARED_SECRET)
    auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    assert client.get(reverse(URL), **auth).status_code == 401
    resp = client.put(
        reverse(URL),
        {
            "changes": [{"role": "analyst", "capability": "ads.review", "state": "grant"}],
            "actor_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **auth,
    )
    assert resp.status_code == 401
    assert not RoleCapability.objects.exists()


# ---- role events for the audit log ------------------------------------------


def _roles_url(account) -> str:
    return reverse("internal-account-roles", args=[account.id])


def test_role_grant_and_revoke_emit_audit_events(client):
    account, actor = _account(), str(uuid.uuid4())
    body = {"role": "moderator", "actor_id": actor}
    client.post(
        _roles_url(account),
        body,
        content_type="application/json",
        HTTP_X_REQUEST_ID="edge-r1",
        **_admin_call(),
    )
    client.post(_roles_url(account), body, content_type="application/json", **_admin_call())
    granted = OutboxEvent.objects.filter(event_type="account.role.granted")
    assert granted.count() == 1  # a duplicate grant decides nothing
    envelope = granted.get().payload
    assert envelope["payload"] == {"account_id": str(account.id), "role": "moderator"}
    assert envelope["actor_id"] == actor
    assert envelope["correlation_id"] == "edge-r1"
    assert "email" not in envelope["payload"]

    client.delete(_roles_url(account), body, content_type="application/json", **_admin_call())
    assert OutboxEvent.objects.filter(event_type="account.role.revoked").count() == 1


def test_audit_events_can_be_switched_off_for_the_first_release(client, settings):
    settings.IDENTITY_EMIT_AUDIT_EVENTS = False
    account = _account()
    resp = client.post(
        _roles_url(account),
        {"role": "analyst", "actor_id": str(uuid.uuid4())},
        content_type="application/json",
        **_admin_call(),
    )
    assert resp.status_code == 201
    assert not OutboxEvent.objects.filter(event_type__startswith="account.role.").exists()


# ---- platform statistics ----------------------------------------------------


def test_stats_count_accounts_behind_an_internal_token(client):
    _account("one@example.com")
    _account("two@example.com", status=Account.Status.DELETED)
    url = reverse("internal-stats")
    assert client.get(url).status_code == 401
    assert client.get(url, **_admin_call(audience="profile-internal")).status_code == 401
    token = mint_internal_token(issuer="admin", audience="identity-internal")
    data = client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}").json()["data"]
    assert data == {"service": settings.SERVICE_NAME, "stats": {"accounts": 1}}
