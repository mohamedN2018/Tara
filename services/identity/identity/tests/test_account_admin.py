"""Admin's user console on identity's internal API (8.6) and suspensions (8.4)."""

import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from identity import account_admin, services
from identity.internal_views import mask_email, mask_phone
from identity.models import (
    Account,
    AccountRole,
    AccountSuspension,
    OutboxEvent,
    RefreshToken,
    SocialIdentity,
    UserSession,
)
from identity.tasks import lift_expired_suspensions
from tara_common.auth import mint_internal_token

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-Pass-987!"
SHARED_SECRET = "shared-internal-secret-every-service-holds-0123456789"
ADMIN_SECRET = "admin-identity-secret-only-admin-holds-0123456789"


@pytest.fixture(autouse=True)
def _distinct_internal_secrets(settings):
    settings.TARA_INTERNAL_JWT_SECRET = SHARED_SECRET
    settings.ADMIN_IDENTITY_SECRET = ADMIN_SECRET


def _account(email="user@example.com", **extra) -> Account:
    extra.setdefault("email_verified", True)
    extra.setdefault("status", Account.Status.ACTIVE)
    return Account.objects.create_user(email=email, password=PASSWORD, **extra)


def _internal(secret=None) -> dict:
    token = mint_internal_token(
        issuer="admin", audience="identity.roles", secret=secret or settings.ADMIN_IDENTITY_SECRET
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _events(event_type: str) -> list[dict]:
    """The envelopes on the outbox for ``event_type``, oldest first."""
    rows = OutboxEvent.objects.filter(event_type=event_type).order_by("created_at")
    return [row.payload for row in rows]


def _suspend(client, account, *, actor=None, key=None, **body):
    return client.post(
        reverse("internal-account-suspension", args=[account.id]),
        {
            "actor_id": str(actor or uuid.uuid4()),
            "reason": "spam reports",
            "idempotency_key": key or uuid.uuid4().hex,
            **body,
        },
        content_type="application/json",
        **_internal(),
    )


# ---- authentication ---------------------------------------------------------------


@pytest.mark.parametrize(
    "name,method,needs_id",
    [
        ("internal-account-search", "get", False),
        ("internal-account-summaries", "post", False),
        ("internal-account-overview", "get", True),
        ("internal-account-personal", "get", True),
        ("internal-account-suspension", "post", True),
        ("internal-account-suspension", "delete", True),
        ("internal-account-sign-out", "post", True),
        ("internal-account-verification", "post", True),
    ],
)
def test_console_endpoints_refuse_the_shared_secret_and_no_token(client, name, method, needs_id):
    account = _account()
    url = reverse(name, args=[account.id]) if needs_id else reverse(name)
    call = getattr(client, method)
    assert call(url).status_code == 401
    assert call(url, **_internal(secret=SHARED_SECRET)).status_code == 401


# ---- search -----------------------------------------------------------------------


def test_search_by_email_prefix_exact_and_id_with_masked_minimal_fields(client):
    layla = _account("layla@example.com")
    _account("layth@example.com")
    _account("omar@example.com")
    url = reverse("internal-account-search")

    prefix = client.get(url, {"q": "LAY"}, **_internal()).json()["data"]
    assert [r["email_masked"] for r in prefix] == ["l****@e******.com", "l****@e******.com"]
    assert set(prefix[0]) == {
        "account_id",
        "email_masked",
        "status",
        "email_verified",
        "created_at",
    }
    assert "layla@example.com" not in str(prefix)

    exact = client.get(url, {"q": "layla@example.com"}, **_internal()).json()["data"]
    assert [r["account_id"] for r in exact] == [str(layla.id)]
    by_id = client.get(url, {"q": str(layla.id)}, **_internal()).json()["data"]
    assert [r["account_id"] for r in by_id] == [str(layla.id)]


def test_search_pages_by_keyset_without_repeats(client):
    for i in range(7):
        _account(f"page{i}@example.com")
    url = reverse("internal-account-search")
    first = client.get(url, {"q": "page", "limit": 3}, **_internal()).json()
    seen = [r["account_id"] for r in first["data"]]
    assert first["page"]["has_more"] is True
    cursor = first["page"]["next_cursor"]
    # An account added mid-walk before the cursor does not shift the next page.
    _account("page0a@example.com")
    while cursor:
        page = client.get(url, {"q": "page", "limit": 3, "cursor": cursor}, **_internal()).json()
        seen += [r["account_id"] for r in page["data"]]
        cursor = page["page"]["next_cursor"]
    assert len(seen) == len(set(seen))
    assert len(seen) in (7, 8)


@pytest.mark.parametrize("q", ["", "a"])
def test_search_needs_an_id_or_two_characters(client, q):
    resp = client.get(reverse("internal-account-search"), {"q": q}, **_internal())
    assert resp.status_code == 400


def test_summaries_keep_the_order_asked_and_skip_unknown_ids(client):
    one, two = _account("one@example.com"), _account("two@example.com")
    resp = client.post(
        reverse("internal-account-summaries"),
        {"ids": [str(two.id), str(uuid.uuid4()), str(one.id)]},
        content_type="application/json",
        **_internal(),
    )
    assert [r["account_id"] for r in resp.json()["data"]] == [str(two.id), str(one.id)]


# ---- overview and personal data -----------------------------------------------------


def test_overview_masks_contact_details_and_counts_live_sessions(client):
    account = _account(phone="+201234567890", phone_verified_at=timezone.now())
    AccountRole.objects.create(account=account, role="analyst")
    SocialIdentity.objects.create(account=account, provider="google", subject="g-1")
    services.login(email=account.email, password=PASSWORD)
    services.login(email=account.email, password=PASSWORD)
    data = client.get(
        reverse("internal-account-overview", args=[account.id]), **_internal()
    ).json()["data"]
    assert data["email_masked"] == mask_email(account.email)
    assert data["phone_masked"] == "+**********90"
    assert data["phone_verified"] is True
    assert data["active_sessions"] == 2
    assert data["roles"] == ["analyst"]
    assert data["google_linked"] is True
    assert data["suspension"] is None
    assert account.email not in str(data) and account.phone not in str(data)


def test_personal_data_has_the_full_email_phone_and_sessions(client):
    account = _account(phone="+201234567890", phone_verified_at=timezone.now())
    services.login(email=account.email, password=PASSWORD, user_agent="Firefox")
    data = client.get(
        reverse("internal-account-personal", args=[account.id]), **_internal()
    ).json()["data"]
    assert data["email"] == account.email
    assert data["phone"] == "+201234567890"
    assert [s["user_agent"] for s in data["sessions"]] == ["Firefox"]


def test_masks():
    assert mask_email("a@b.co") == "a*@b*.co"
    assert mask_email("layla@mail.example.com") == "l****@m***********.com"
    assert mask_phone("+201234567890") == "+**********90"
    assert mask_phone("") == ""


# ---- suspension ---------------------------------------------------------------------


def test_a_suspended_account_cannot_log_in_or_refresh_and_its_tokens_are_revoked(client):
    account = _account()
    issued = services.login(email=account.email, password=PASSWORD)
    other = services.login(email=account.email, password=PASSWORD)
    until = timezone.now() + timedelta(days=3)

    resp = _suspend(client, account, until=until.isoformat())
    assert resp.status_code == 201
    account.refresh_from_db()
    assert account.status == Account.Status.SUSPENDED
    assert RefreshToken.objects.filter(account=account, revoked_at__isnull=True).count() == 0
    assert UserSession.objects.filter(account=account, revoked_at__isnull=True).count() == 0

    login = client.post(
        reverse("identity:login"),
        {"email": account.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert login.status_code == 403
    for raw in (issued.refresh_token, other.refresh_token):
        refresh = client.post(
            reverse("identity:refresh"), {"refresh_token": raw}, content_type="application/json"
        )
        assert refresh.status_code == 401

    [event] = _events("account.suspended")
    assert event["payload"] == {
        "account_id": str(account.id),
        "until": until.isoformat(),
        "suspension_id": resp.json()["data"]["suspension"]["id"],
        "source": "admin",
    }
    assert "spam" not in str(event)  # the reason stays in identity


def test_the_same_idempotency_key_suspends_once(client):
    account = _account()
    first = _suspend(client, account, key="retry-key-0001")
    again = _suspend(client, account, key="retry-key-0001")
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["data"]["suspension"]["id"] == first.json()["data"]["suspension"]["id"]
    assert AccountSuspension.objects.count() == 1
    assert len(_events("account.suspended")) == 1
    # The key cannot be replayed against another account.
    assert _suspend(client, _account("b@example.com"), key="retry-key-0001").status_code == 409


def test_nobody_suspends_themselves_a_staff_account_or_an_already_suspended_one(client):
    account = _account()
    assert _suspend(client, account, actor=account.id).status_code == 400
    staff = _account("mod@example.com")
    AccountRole.objects.create(account=staff, role="moderator")
    assert _suspend(client, staff).status_code == 409
    superuser = _account("root@example.com", is_superuser=True)
    assert _suspend(client, superuser).status_code == 409
    assert _suspend(client, account).status_code == 201
    assert _suspend(client, account).status_code == 409
    past = (timezone.now() - timedelta(minutes=1)).isoformat()
    assert _suspend(client, _account("c@example.com"), until=past).status_code == 400


def test_unsuspend_restores_the_previous_status_and_login_works(client):
    account = _account()
    _suspend(client, account)
    resp = client.delete(
        reverse("internal-account-suspension", args=[account.id]),
        {"actor_id": str(uuid.uuid4()), "reason": "appeal accepted"},
        content_type="application/json",
        **_internal(),
    )
    assert resp.status_code == 200
    account.refresh_from_db()
    assert account.status == Account.Status.ACTIVE
    assert services.login(email=account.email, password=PASSWORD).access_token
    [event] = _events("account.unsuspended")
    assert event["payload"]["expired"] is False
    # Nothing left to lift.
    again = client.delete(
        reverse("internal-account-suspension", args=[account.id]),
        {"actor_id": str(uuid.uuid4()), "reason": "again"},
        content_type="application/json",
        **_internal(),
    )
    assert again.status_code == 409


def test_a_pending_account_goes_back_to_pending():
    account = _account(status=Account.Status.PENDING, email_verified=False)
    account_admin.suspend(
        account.id, actor_id=uuid.uuid4(), reason="r", until=None, idempotency_key="pending-01"
    )
    account_admin.unsuspend(account.id, actor_id=uuid.uuid4(), reason="r")
    account.refresh_from_db()
    assert account.status == Account.Status.PENDING


def _expired_suspension(account: Account) -> AccountSuspension:
    suspension, _ = account_admin.suspend(
        account.id,
        actor_id=uuid.uuid4(),
        reason="cool off",
        until=timezone.now() + timedelta(hours=1),
        idempotency_key=uuid.uuid4().hex,
    )
    # An `until` in the past, as if the hour went by.
    AccountSuspension.objects.filter(id=suspension.id).update(
        until=timezone.now() - timedelta(seconds=1)
    )
    return suspension


def test_the_beat_task_lifts_a_suspension_past_its_end_date():
    account = _account()
    suspension = _expired_suspension(account)
    still = _expired_suspension(_account("later@example.com"))
    AccountSuspension.objects.filter(id=still.id).update(until=timezone.now() + timedelta(days=1))

    assert lift_expired_suspensions() == 1
    account.refresh_from_db()
    suspension.refresh_from_db()
    assert account.status == Account.Status.ACTIVE
    assert suspension.lifted_at is not None and suspension.lifted_by is None
    [event] = _events("account.unsuspended")
    assert event["payload"]["expired"] is True
    assert event["actor_id"] is None
    assert Account.objects.get(email="later@example.com").status == Account.Status.SUSPENDED


def test_login_itself_lifts_an_expired_suspension(client):
    account = _account()
    _expired_suspension(account)
    login = client.post(
        reverse("identity:login"),
        {"email": account.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert login.status_code == 200
    account.refresh_from_db()
    assert account.status == Account.Status.ACTIVE


def test_suspension_events_commit_with_the_state_change(monkeypatch):
    """The outbox row is in the suspension's transaction: one fails, both roll back."""
    account = _account()
    services.login(email=account.email, password=PASSWORD)

    def broken(*args, **kwargs):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(account_admin, "emit_domain_event", broken)
    with pytest.raises(RuntimeError):
        account_admin.suspend(
            account.id, actor_id=uuid.uuid4(), reason="r", until=None, idempotency_key="atomic-01"
        )
    account.refresh_from_db()
    assert account.status == Account.Status.ACTIVE
    assert not AccountSuspension.objects.exists()
    assert UserSession.objects.filter(account=account, revoked_at__isnull=True).count() == 1

    monkeypatch.undo()
    account_admin.suspend(
        account.id, actor_id=uuid.uuid4(), reason="r", until=None, idempotency_key="atomic-02"
    )
    monkeypatch.setattr(account_admin, "emit_domain_event", broken)
    with pytest.raises(RuntimeError):
        account_admin.unsuspend(account.id, actor_id=uuid.uuid4(), reason="r")
    account.refresh_from_db()
    assert account.status == Account.Status.SUSPENDED
    assert AccountSuspension.objects.get().lifted_at is None


def test_emission_flag_off_keeps_the_suspension_but_emits_nothing(settings):
    settings.IDENTITY_EMIT_ACCOUNT_ACTION_EVENTS = False
    account = _account()
    account_admin.suspend(
        account.id, actor_id=uuid.uuid4(), reason="r", until=None, idempotency_key="flag-off-1"
    )
    account.refresh_from_db()
    assert account.status == Account.Status.SUSPENDED
    assert _events("account.suspended") == []


# ---- sign-out and verification ------------------------------------------------------


def test_sign_out_everywhere_revokes_every_session(client):
    account = _account()
    issued = services.login(email=account.email, password=PASSWORD)
    services.login(email=account.email, password=PASSWORD)
    resp = client.post(
        reverse("internal-account-sign-out", args=[account.id]),
        {"actor_id": str(uuid.uuid4())},
        content_type="application/json",
        **_internal(),
    )
    assert resp.json()["data"] == {"sessions_revoked": 2}
    refresh = client.post(
        reverse("identity:refresh"),
        {"refresh_token": issued.refresh_token},
        content_type="application/json",
    )
    assert refresh.status_code == 401
    [event] = _events("account.signed_out")
    assert event["payload"] == {"account_id": str(account.id), "sessions": 2}
    # The account itself stays usable.
    assert services.login(email=account.email, password=PASSWORD).access_token


def test_sign_out_refuses_self_and_admin_accounts(client):
    admin = _account("admin@example.com", is_superuser=True)
    url = reverse("internal-account-sign-out", args=[admin.id])
    body = {"actor_id": str(uuid.uuid4())}
    assert client.post(url, body, content_type="application/json", **_internal()).status_code == 409
    me = _account()
    resp = client.post(
        reverse("internal-account-sign-out", args=[me.id]),
        {"actor_id": str(me.id)},
        content_type="application/json",
        **_internal(),
    )
    assert resp.status_code == 400


def test_resend_verification_sends_a_link_once_a_minute_and_not_when_verified(
    client, django_capture_on_commit_callbacks
):
    pending = _account("new@example.com", status=Account.Status.PENDING, email_verified=False)
    url = reverse("internal-account-verification", args=[pending.id])
    body = {"actor_id": str(uuid.uuid4())}
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(url, body, content_type="application/json", **_internal())
    assert resp.status_code == 202
    assert [m.to for m in mail.outbox] == [["new@example.com"]]
    assert client.post(url, body, content_type="application/json", **_internal()).status_code == 429
    assert len(_events("account.verification.resent")) == 1

    verified = _account()
    url = reverse("internal-account-verification", args=[verified.id])
    assert client.post(url, body, content_type="application/json", **_internal()).status_code == 409
