"""Admin: feature flags + role management RBAC + role registry."""

import uuid

import pytest
from django.urls import reverse

from adminsvc.models import AccountRole, FeatureFlag

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


def test_role_grant_and_revoke_admin_only(client_for):
    target = _acct()
    admin = client_for(_acct(), roles=["admin"])
    granted = admin.post(
        reverse("adminsvc:roles"), {"account_id": target, "role": "moderator"}, format="json"
    )
    assert granted.status_code == 201
    assert AccountRole.objects.filter(account_id=target, role="moderator").exists()

    listing = admin.get(reverse("adminsvc:account-roles", args=[target]))
    assert "moderator" in listing.json()["data"]["roles"]

    revoked = admin.delete(
        reverse("adminsvc:roles"), {"account_id": target, "role": "moderator"}, format="json"
    )
    assert revoked.status_code == 200
    assert not AccountRole.objects.filter(account_id=target, role="moderator").exists()


def test_non_admin_cannot_manage_roles(client_for):
    resp = client_for(_acct(), roles=["moderator"]).post(
        reverse("adminsvc:roles"), {"account_id": _acct(), "role": "admin"}, format="json"
    )
    assert resp.status_code == 403


def test_internal_roles_requires_internal_token():
    from rest_framework.test import APIClient

    from adminsvc.services import grant_role

    target = _acct()
    grant_role(target, "moderator", _acct())
    client = APIClient()
    url = reverse("internal-roles", args=[target])
    assert client.get(url).status_code == 401

    import time as _t

    from django.conf import settings

    now = int(_t.time())
    token = jwt_encode(now, settings.TARA_INTERNAL_JWT_SECRET)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    ok = client.get(url)
    assert ok.status_code == 200
    assert ok.json()["data"]["roles"] == ["moderator"]


def jwt_encode(now: int, secret: str) -> str:
    import jwt

    return jwt.encode(
        {"iss": "identity", "aud": "admin-internal", "iat": now, "exp": now + 30},
        secret,
        algorithm="HS256",
    )
