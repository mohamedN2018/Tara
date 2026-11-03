"""User management console (8.6): search, the audited account page and reveal, actions."""

import uuid
from datetime import timedelta

import pytest
import requests
from django.urls import reverse
from django.utils import timezone

from adminsvc import handlers
from adminsvc.models import AuditEntry
from tara_common.exceptions import Conflict, DependencyUnavailable, TaraAPIError
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

VIEW = "admin.users.view"
ALL_USER_CAPS = [
    VIEW,
    "admin.users.reveal",
    "admin.users.suspend",
    "admin.users.sign_out",
    "admin.users.resend_verification",
]


def _acct() -> str:
    return str(uuid.uuid4())


class FakeIdentity:
    """Identity's console endpoints, as admin's client sees them."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.accounts = {}
        self.personal_down = False

    def add(self, email="layla@example.com", status="active") -> str:
        account_id = _acct()
        self.accounts[account_id] = {
            "account_id": account_id,
            "email_masked": "l****@e******.com",
            "email": email,
            "status": status,
            "email_verified": True,
            "created_at": "2026-11-01T10:00:00+00:00",
        }
        return account_id

    def _summary(self, account_id):
        a = self.accounts[account_id]
        return {k: v for k, v in a.items() if k != "email"}

    def search_accounts(self, q, cursor=None, limit=None):
        self.calls.append(("search", q, cursor, limit))
        ids = sorted(self.accounts)
        if cursor == "page-2":
            return {"data": [self._summary(ids[-1])], "page": {"has_more": False}}
        return {
            "data": [self._summary(i) for i in ids[:-1]],
            "page": {"next_cursor": "page-2", "prev_cursor": None, "has_more": True},
        }

    def account_summaries(self, ids):
        self.calls.append(("summaries", tuple(ids)))
        return [self._summary(i) for i in ids if i in self.accounts]

    def account_overview(self, account_id):
        if account_id not in self.accounts:
            raise TaraAPIError("Account not found.", code="not_found", http_status_code=404)
        return {**self._summary(account_id), "roles": [], "active_sessions": 2, "suspension": None}

    def account_personal_data(self, account_id):
        if self.personal_down:
            raise DependencyUnavailable("Identity is unavailable.")
        self.calls.append(("personal", account_id))
        return {"account_id": account_id, "email": self.accounts[account_id]["email"], "phone": ""}

    def suspend(self, account_id, *, actor_id, reason, until, idempotency_key):
        self.calls.append(("suspend", account_id, actor_id, reason, until, idempotency_key))
        return {"suspension": {"id": _acct(), "until": until}, "created": True}

    def unsuspend(self, account_id, *, actor_id, reason):
        self.calls.append(("unsuspend", account_id, reason))
        return {"lifted": True}

    def sign_out_everywhere(self, account_id, *, actor_id):
        self.calls.append(("sign_out", account_id))
        return {"sessions_revoked": 2}

    def resend_verification(self, account_id, *, actor_id):
        self.calls.append(("resend", account_id))
        raise Conflict("This email is already verified.", code="conflict")


@pytest.fixture
def identity(monkeypatch):
    fake = FakeIdentity()
    for name in (
        "search_accounts",
        "account_summaries",
        "account_overview",
        "account_personal_data",
        "suspend",
        "unsuspend",
        "sign_out_everywhere",
        "resend_verification",
    ):
        monkeypatch.setattr(f"adminsvc.identity_client.{name}", getattr(fake, name))
    return fake


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def services_up(monkeypatch):
    """Profile and the per-account counters answer; ``down`` lists services that don't."""
    seen: list[tuple] = []
    down: set[str] = set()

    def fake(method, url, **kwargs):
        seen.append((method, url, kwargs.get("params"), kwargs.get("json")))
        host = url.split("//", 1)[1].split(":", 1)[0]
        if host in down:
            raise requests.ConnectionError("down")
        if "/profiles/by-account/" in url:
            ids = kwargs["json"]["account_ids"]
            return _Resp(
                200, {"data": {i: {"handle": "layla", "display_name": "Layla"} for i in ids}}
            )
        if "/profiles/search/" in url:
            return _Resp(200, {"data": [], "page": {"has_more": False}})
        if "/snapshot/" in url:
            return _Resp(200, {"data": {"handle": "layla", "display_name": "Layla", "bio": "x"}})
        if "/stats/accounts/" in url:
            metric = {"post": "posts", "marketplace": "listings", "moderation": "open_cases"}[host]
            return _Resp(200, {"data": {"stats": {metric: 3}}})
        return _Resp(404, {})

    monkeypatch.setattr("adminsvc.users.requests.request", fake)
    # A circuit opened by an earlier test must not leak into this one.
    monkeypatch.setattr("adminsvc.users._breakers", {})
    fake.seen, fake.down = seen, down
    return fake


# ---- capabilities -----------------------------------------------------------------

ENDPOINTS = [
    ("get", "adminsvc:users", False, VIEW),
    ("get", "adminsvc:user-detail", True, VIEW),
    ("post", "adminsvc:user-reveal", True, "admin.users.reveal"),
    ("post", "adminsvc:user-suspend", True, "admin.users.suspend"),
    ("post", "adminsvc:user-unsuspend", True, "admin.users.suspend"),
    ("post", "adminsvc:user-sign-out", True, "admin.users.sign_out"),
    ("post", "adminsvc:user-resend-verification", True, "admin.users.resend_verification"),
]


# DRF marks the surrounding transaction for rollback on an error response. These
# views are non-atomic, so in production there is none; under the test's own
# transaction there is, so tests that query after a refusal run without it.
_no_wrapping_transaction = pytest.mark.django_db(transaction=True)


@_no_wrapping_transaction
@pytest.mark.parametrize("method,name,needs_id,cap", ENDPOINTS)
def test_each_endpoint_needs_its_own_capability(client_for, identity, method, name, needs_id, cap):
    url = reverse(name, args=[_acct()]) if needs_id else reverse(name)
    others = [c for c in ALL_USER_CAPS if c != cap and c != VIEW] + ["admin.roles.manage"]
    if cap == VIEW:
        others = ["admin.roles.manage", "admin.audit.view"]
    for caps in ([], others):
        resp = getattr(client_for(_acct(), caps=caps), method)(url, {"q": "layla"})
        assert resp.status_code == 403, (name, caps)
    # A moderator by default has none of them; an admin token has them all.
    assert getattr(client_for(_acct(), roles=["moderator"]), method)(url).status_code == 403
    assert identity.calls == []
    assert not AuditEntry.objects.exists()


def test_admin_role_holds_every_user_capability():
    from tara_common import capabilities as registry

    assert set(ALL_USER_CAPS) <= registry.capabilities_for_roles(["admin"])
    for cap in ALL_USER_CAPS[1:]:
        assert VIEW in registry.with_implied([cap])
    assert not set(ALL_USER_CAPS) & registry.capabilities_for_roles(["moderator", "analyst"])


# ---- search -----------------------------------------------------------------------


def test_email_search_pages_with_identitys_cursor_and_adds_profile_names(
    client_for, identity, services_up
):
    for i in range(3):
        identity.add(f"layla{i}@example.com")
    staff = client_for(_acct(), caps=[VIEW])
    first = staff.get(reverse("adminsvc:users"), {"q": "layla@", "limit": 2}).json()
    assert first["field"] == "email"
    assert first["page"] == {"next_cursor": "page-2", "prev_cursor": None, "has_more": True}
    assert set(first["data"][0]) == {
        "account_id",
        "email_masked",
        "status",
        "email_verified",
        "created_at",
        "handle",
        "display_name",
    }
    assert first["data"][0]["handle"] == "layla"
    second = staff.get(reverse("adminsvc:users"), {"q": "layla@", "cursor": "page-2"}).json()
    assert second["page"]["has_more"] is False
    seen = [r["account_id"] for r in first["data"] + second["data"]]
    assert sorted(seen) == sorted(identity.accounts)
    assert ("search", "layla@", "page-2", 20) in identity.calls
    # Search results never carry the full address.
    assert "example.com" not in str(first) + str(second)


def test_auto_field_picks_id_email_handle_or_name(client_for, identity, services_up):
    account = identity.add()
    staff = client_for(_acct(), caps=[VIEW])
    assert staff.get(reverse("adminsvc:users"), {"q": account}).json()["field"] == "id"
    assert staff.get(reverse("adminsvc:users"), {"q": "@layla"}).json()["field"] == "handle"
    assert staff.get(reverse("adminsvc:users"), {"q": "ليلى"}).json()["field"] == "any"
    by_name = staff.get(reverse("adminsvc:users"), {"q": "lay", "field": "name"})
    assert by_name.json()["field"] == "name"
    profile_searches = [s for s in services_up.seen if "/profiles/search/" in s[1]]
    assert [p[2]["field"] for p in profile_searches] == ["handle", "any", "name"]


def test_handle_search_joins_identity_status_in_profile_order(
    client_for, identity, services_up, monkeypatch
):
    one, two = identity.add("a@example.com"), identity.add("b@example.com", status="suspended")
    gone = _acct()  # a profile whose account identity no longer has

    def fake(method, url, **kwargs):
        return _Resp(
            200,
            {
                "data": [
                    {"account_id": two, "handle": "bee", "display_name": "B"},
                    {"account_id": gone, "handle": "ghost", "display_name": ""},
                    {"account_id": one, "handle": "eh", "display_name": "A"},
                ],
                "page": {"next_cursor": "c2", "has_more": True},
            },
        )

    monkeypatch.setattr("adminsvc.users.requests.request", fake)
    resp = client_for(_acct(), caps=[VIEW]).get(reverse("adminsvc:users"), {"q": "@b"}).json()
    assert [(r["handle"], r["status"]) for r in resp["data"]] == [
        ("bee", "suspended"),
        ("eh", "active"),
    ]
    assert resp["page"]["next_cursor"] == "c2"


def test_handle_search_says_so_when_profile_is_down(client_for, identity, services_up):
    services_up.down.add("profile")
    resp = client_for(_acct(), caps=[VIEW]).get(reverse("adminsvc:users"), {"q": "@layla"})
    assert resp.status_code == 503


@pytest.mark.parametrize("q", ["", "a"])
def test_search_needs_two_characters(client_for, identity, q):
    resp = client_for(_acct(), caps=[VIEW]).get(reverse("adminsvc:users"), {"q": q})
    assert resp.status_code == 400


# ---- the account page: every view is audited --------------------------------------


def test_every_detail_view_writes_an_audit_entry(client_for, identity, services_up):
    account = identity.add()
    me = _acct()
    staff = client_for(me, caps=[VIEW])
    for _ in range(2):
        resp = staff.get(reverse("adminsvc:user-detail", args=[account]))
        assert resp.status_code == 200
        assert resp["Cache-Control"] == "no-store"
    data = resp.json()["data"]
    assert data["profile"] == {"handle": "layla", "display_name": "Layla", "avatar_media_id": None}
    assert data["counts"] == {"posts": 3, "listings": 3, "open_cases": 3}
    assert "email" not in data  # masked only until revealed
    entries = AuditEntry.objects.filter(action="user.viewed")
    assert entries.count() == 2
    assert {(str(e.actor_id), e.target_type, e.target_id) for e in entries} == {
        (me, "account", account)
    }


def test_detail_survives_profile_and_counters_being_down(client_for, identity, services_up):
    account = identity.add()
    services_up.down.update({"profile", "post", "marketplace", "moderation"})
    resp = client_for(_acct(), caps=[VIEW]).get(reverse("adminsvc:user-detail", args=[account]))
    assert resp.status_code == 200
    assert resp.json()["data"]["profile"] is None
    assert resp.json()["data"]["counts"] == {"posts": None, "listings": None, "open_cases": None}
    assert AuditEntry.objects.filter(action="user.viewed").count() == 1


def test_an_unknown_account_is_404_and_not_audited(client_for, identity, services_up):
    resp = client_for(_acct(), caps=[VIEW]).get(reverse("adminsvc:user-detail", args=[_acct()]))
    assert resp.status_code == 404
    assert not AuditEntry.objects.exists()


# ---- reveal -----------------------------------------------------------------------


def test_reveal_writes_an_audit_entry_with_the_typed_reason(client_for, identity):
    account = identity.add("layla@example.com")
    me = _acct()
    staff = client_for(me, caps=["admin.users.reveal"])
    url = reverse("adminsvc:user-reveal", args=[account])
    resp = staff.post(url, {"reason": "Ticket 4411: owner asked"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == "layla@example.com"
    assert resp["Cache-Control"] == "no-store"
    entry = AuditEntry.objects.get(action="user.personal_data.revealed")
    assert (str(entry.actor_id), entry.target_type, entry.target_id) == (me, "account", account)
    assert entry.reason == "Ticket 4411: owner asked"
    assert entry.detail == {"fields": ["email", "phone", "sessions"]}
    # The audit list shows the reason to auditors.
    listed = client_for(_acct(), caps=["admin.audit.view"]).get(
        reverse("adminsvc:audit"), {"target_id": account}
    )
    assert listed.json()["data"][0]["reason"] == "Ticket 4411: owner asked"


@_no_wrapping_transaction
@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "abc"}, {"reason": "x" * 501}])
def test_reveal_needs_a_reason_and_without_one_nothing_is_shown(client_for, identity, body):
    account = identity.add()
    staff = client_for(_acct(), caps=["admin.users.reveal"])
    resp = staff.post(reverse("adminsvc:user-reveal", args=[account]), body, format="json")
    assert resp.status_code == 400
    assert ("personal", account) not in identity.calls
    assert not AuditEntry.objects.exists()


def test_reveal_that_identity_cannot_answer_is_not_audited_as_seen(client_for, identity):
    account = identity.add()
    identity.personal_down = True
    staff = client_for(_acct(), caps=["admin.users.reveal"])
    resp = staff.post(
        reverse("adminsvc:user-reveal", args=[account]), {"reason": "support ticket"}, format="json"
    )
    assert resp.status_code == 503
    assert not AuditEntry.objects.exists()


# ---- actions ----------------------------------------------------------------------


def test_suspend_forwards_reason_end_date_and_a_prefixed_idempotency_key(client_for, identity):
    account = identity.add()
    me = _acct()
    until = timezone.now() + timedelta(days=7)
    resp = client_for(me, caps=["admin.users.suspend"]).post(
        reverse("adminsvc:user-suspend", args=[account]),
        {"reason": "spam campaign", "until": until.isoformat()},
        format="json",
        HTTP_IDEMPOTENCY_KEY="dialog-key-123",
    )
    assert resp.status_code == 201
    [call] = [c for c in identity.calls if c[0] == "suspend"]
    assert call[1:4] == (account, me, "spam campaign")
    assert call[4] == until.isoformat()
    assert call[5] == "admin:dialog-key-123"


def test_suspend_refuses_a_past_end_date_and_oneself(client_for, identity):
    account = identity.add()
    me = _acct()
    staff = client_for(me, caps=["admin.users.suspend"])
    past = (timezone.now() - timedelta(minutes=5)).isoformat()
    url = reverse("adminsvc:user-suspend", args=[account])
    assert staff.post(url, {"reason": "spam!", "until": past}, format="json").status_code == 400
    own = reverse("adminsvc:user-suspend", args=[me])
    assert staff.post(own, {"reason": "spam!"}, format="json").status_code == 400
    assert not [c for c in identity.calls if c[0] == "suspend"]


def test_unsuspend_sign_out_and_resend_reach_identity(client_for, identity):
    account = identity.add()
    staff = client_for(_acct(), caps=ALL_USER_CAPS)
    resp = staff.post(
        reverse("adminsvc:user-unsuspend", args=[account]), {"reason": "appeal won"}, format="json"
    )
    assert resp.status_code == 200
    assert staff.post(reverse("adminsvc:user-sign-out", args=[account])).json()["data"] == {
        "sessions_revoked": 2
    }
    # Identity's refusal (already verified) comes through as a 409.
    resend = staff.post(reverse("adminsvc:user-resend-verification", args=[account]))
    assert resend.status_code == 409
    assert [c[0] for c in identity.calls] == ["unsuspend", "sign_out", "resend"]


def test_identity_client_passes_conflicts_and_throttles_through(monkeypatch, settings):
    from adminsvc import identity_client

    def fake(method, url, **kwargs):
        status = 409 if "suspension" in url else 429
        return type(
            "R",
            (),
            {
                "status_code": status,
                "ok": False,
                "json": lambda self: {"error": {"message": "nope"}},
            },
        )()

    monkeypatch.setattr("adminsvc.identity_client.requests.request", fake)
    with pytest.raises(Conflict):
        identity_client.unsuspend(_acct(), actor_id=_acct(), reason="r")
    with pytest.raises(TaraAPIError) as exc:
        identity_client.resend_verification(_acct(), actor_id=_acct())
    assert exc.value.http_status == 429


# ---- the audit consumer records the suspension events -----------------------------


def _env(event_type, payload, actor=None):
    return EventEnvelope(
        event_type=event_type,
        payload=payload,
        subject_id=payload["account_id"],
        producer="identity-service",
        actor_id=actor,
        correlation_id="req-123",
    )


def test_suspension_events_become_audit_entries_once():
    account, staff, suspension = _acct(), _acct(), _acct()
    until = "2026-12-01T00:00:00+00:00"
    env = _env(
        "account.suspended",
        {"account_id": account, "until": until, "suspension_id": suspension, "source": "admin"},
        actor=staff,
    )
    handlers.audit_account_suspended(env)
    handlers.audit_account_suspended(env)  # redelivered
    lifted = _env(
        "account.unsuspended",
        {"account_id": account, "suspension_id": suspension, "expired": True},
    )
    handlers.audit_account_unsuspended(lifted)
    handlers.audit_account_signed_out(
        _env("account.signed_out", {"account_id": account, "sessions": 3}, actor=staff)
    )
    handlers.audit_account_verification_resent(
        _env("account.verification.resent", {"account_id": account}, actor=staff)
    )

    rows = {e.action: e for e in AuditEntry.objects.filter(target_id=account)}
    assert set(rows) == {
        "account.suspended",
        "account.unsuspended",
        "account.signed_out",
        "account.verification_resent",
    }
    assert AuditEntry.objects.filter(action="account.suspended").count() == 1
    suspended = rows["account.suspended"]
    assert (str(suspended.actor_id), suspended.target_type) == (staff, "account")
    assert suspended.detail == {"suspension_id": suspension, "until": until, "source": "admin"}
    assert suspended.request_id == "req-123"
    expired = rows["account.unsuspended"]
    assert expired.actor_kind == "system" and expired.actor_name == "identity-service"
    assert expired.detail == {"suspension_id": suspension, "expired": True}
    assert rows["account.signed_out"].detail == {"sessions": 3}
