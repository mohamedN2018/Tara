"""A suspended member learns, at sign-in, that and until when they are suspended (T7)."""

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from identity import account_admin
from identity.models import Account

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-Pass-987!"


def _account(email="member@example.com") -> Account:
    return Account.objects.create_user(
        email=email, password=PASSWORD, email_verified=True, status=Account.Status.ACTIVE
    )


def _login(client, email, password=PASSWORD):
    return client.post(
        reverse("identity:login"),
        {"email": email, "password": password},
        content_type="application/json",
    )


def _details(resp) -> dict:
    return {d["field"]: d for d in resp.json()["error"]["details"]}


def test_a_suspended_member_sees_until_when_but_not_the_staff_note(client):
    account = _account()
    until = timezone.now() + timedelta(days=3)
    account_admin.suspend(
        account.id,
        actor_id=uuid.uuid4(),
        reason="internal staff note",
        until=until,
        idempotency_key="t7-suspend-0001",
    )
    resp = _login(client, account.email)
    assert resp.status_code == 403
    error = resp.json()["error"]
    assert error["code"] == "account_suspended"
    details = _details(resp)
    assert details["until"]["message"] == until.isoformat()
    assert details["source"]["code"] == "admin"
    assert "internal staff note" not in resp.content.decode()


def test_an_open_ended_suspension_has_no_end_date(client):
    account = _account()
    account_admin.suspend(
        account.id, actor_id=uuid.uuid4(), reason="r", until=None, idempotency_key="t7-suspend-0002"
    )
    resp = _login(client, account.email)
    assert resp.json()["error"]["code"] == "account_suspended"
    assert _details(resp)["until"]["message"] == ""


def test_a_wrong_password_never_reveals_the_suspension(client):
    account = _account()
    account_admin.suspend(
        account.id, actor_id=uuid.uuid4(), reason="r", until=None, idempotency_key="t7-suspend-0003"
    )
    resp = _login(client, account.email, password="Wrong-Pass-123!")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "authentication_failed"


def test_other_blocked_accounts_keep_the_generic_error(client):
    account = _account()
    Account.objects.filter(id=account.id).update(status=Account.Status.DEACTIVATED, is_active=False)
    resp = _login(client, account.email)
    assert resp.status_code in (401, 403)
    assert resp.json()["error"]["code"] != "account_suspended"
