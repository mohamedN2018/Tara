"""Who holds a capability (fix round 3): chat asks who answers the support
inbox, to tell them of a new support message. Chat's own secret only; ids only."""

import pytest
from django.conf import settings
from django.urls import reverse

from identity.models import Account, AccountRole, RoleCapability
from tara_common.auth import mint_internal_token

pytestmark = pytest.mark.django_db

SHARED_SECRET = "shared-internal-secret-every-service-holds-0123456789"
ADMIN_SECRET = "admin-identity-secret-only-admin-holds-0123456789"
CHAT_SECRET = "chat-identity-secret-only-chat-holds-0123456789"
URL = "internal-capability-holders"
SUPPORT = "moderation.case.view"


@pytest.fixture(autouse=True)
def _distinct_internal_secrets(settings):
    settings.TARA_INTERNAL_JWT_SECRET = SHARED_SECRET
    settings.ADMIN_IDENTITY_SECRET = ADMIN_SECRET
    settings.CHAT_IDENTITY_SECRET = CHAT_SECRET


def _account(email, **extra) -> Account:
    extra.setdefault("email_verified", True)
    extra.setdefault("status", Account.Status.ACTIVE)
    return Account.objects.create_user(email=email, password="Str0ng-Pass-987!", **extra)


def _as(issuer="chat", secret=None, audience="identity.roles") -> dict:
    token = mint_internal_token(
        issuer=issuer, audience=audience, secret=secret or settings.CHAT_IDENTITY_SECRET
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _holders(client, capability=SUPPORT, **headers):
    return client.get(reverse(URL), {"capability": capability}, **(headers or _as()))


def test_lists_the_active_accounts_that_hold_the_capability(client):
    moderator = _account("mod@example.com")
    AccountRole.objects.create(account=moderator, role="moderator")
    admin = _account("admin@example.com")
    AccountRole.objects.create(account=admin, role="admin")
    staff_flag = _account("staff@example.com", is_staff=True)  # bridged to moderator
    reviewer = _account("ads@example.com")
    AccountRole.objects.create(account=reviewer, role="ad_reviewer")
    gone = _account("gone@example.com", status=Account.Status.DEACTIVATED)
    AccountRole.objects.create(account=gone, role="moderator")
    _account("member@example.com")

    resp = _holders(client)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["capability"] == SUPPORT
    assert sorted(data["account_ids"]) == sorted(str(a.id) for a in (moderator, admin, staff_flag))
    # Ids only: no emails or roles leave identity.
    assert "@example.com" not in resp.content.decode()


def test_follows_the_capability_matrix(client):
    analyst = _account("analyst@example.com")
    AccountRole.objects.create(account=analyst, role="analyst")
    moderator = _account("mod@example.com")
    AccountRole.objects.create(account=moderator, role="moderator")
    assert _holders(client).json()["data"]["account_ids"] == [str(moderator.id)]
    # A matrix grant reaches the list (as it reaches the caps claim).
    RoleCapability.objects.create(role="analyst", capability=SUPPORT, granted=True)
    holders = _holders(client).json()["data"]["account_ids"]
    assert sorted(holders) == sorted([str(analyst.id), str(moderator.id)])


def test_staff_without_two_factor_are_left_out_when_it_is_required(client, settings):
    moderator = _account("mod@example.com")
    AccountRole.objects.create(account=moderator, role="moderator")
    settings.STAFF_REQUIRE_2FA = True
    assert _holders(client).json()["data"]["account_ids"] == []


def test_only_chat_with_its_own_secret_and_only_the_support_capability(client):
    moderator = _account("mod@example.com")
    AccountRole.objects.create(account=moderator, role="moderator")
    # The shared secret, admin's secret, or admin as the caller: refused.
    for headers in (
        _as(secret=SHARED_SECRET),
        _as(secret=ADMIN_SECRET),
        _as(issuer="admin", secret=ADMIN_SECRET),
        _as(audience="profile-internal"),
    ):
        assert _holders(client, **headers).status_code == 401
    assert client.get(reverse(URL), {"capability": SUPPORT}).status_code == 401
    # Any other capability: not listable.
    assert _holders(client, capability="admin.users.view").status_code == 400
    assert _holders(client, capability="").status_code == 400


def test_chat_cannot_reach_the_admin_only_role_api(client):
    resp = client.get(reverse("internal-role-holders"), **_as())
    assert resp.status_code == 401


def test_no_chat_secret_fails_closed(client, settings):
    moderator = _account("mod@example.com")
    AccountRole.objects.create(account=moderator, role="moderator")
    headers = _as()
    settings.CHAT_IDENTITY_SECRET = ""
    assert _holders(client, **headers).status_code == 401
