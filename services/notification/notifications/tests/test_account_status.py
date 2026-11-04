"""Account status notifications and administrative notices (track T7)."""

import uuid

import pytest

from notifications import moderation_handlers, registry
from notifications.models import Notification
from tara_events.dispatch import handlers_for
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _env(event_type: str, payload: dict, actor: str | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        subject_id=payload.get("case_id") or payload.get("notice_id") or _acct(),
        producer="test",
        payload=payload,
        actor_id=actor or _acct(),
    )


@pytest.mark.parametrize("action", ["remove", "warn", "restrict"])
def test_the_owner_hears_about_a_decision(action):
    owner, case_id, post_id = _acct(), _acct(), _acct()
    moderation_handlers.on_moderation_decision(
        _env(
            "moderation.actioned",
            {
                "case_id": case_id,
                "target_type": "post",
                "target_id": post_id,
                "action": action,
                "owner_id": owner,
            },
        )
    )
    (row,) = Notification.objects.filter(kind="moderation.decision")
    assert str(row.recipient_id) == owner
    assert row.actor_id is None  # no moderator is named
    assert row.category == "account"
    assert row.data == {"case_id": case_id, "decision": action, "target_type": "post"}
    assert registry.url_for(row) == f"/support?case={case_id}"


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "shadow", "owner_id": "x"},  # never announced
        {"action": "dismiss", "owner_id": "x"},
        {"action": "approve", "owner_id": "x"},
        {"action": "remove", "owner_id": None},  # an owner nobody knows
        {"action": "remove"},  # an event from before owner_id
    ],
)
def test_other_decisions_reach_nobody(payload):
    if payload.get("owner_id") == "x":
        payload["owner_id"] = _acct()
    moderation_handlers.on_moderation_decision(
        _env("moderation.actioned", {"case_id": _acct(), "target_type": "user", **payload})
    )
    assert not Notification.objects.exists()


@pytest.mark.parametrize("status", ["upheld", "overturned"])
def test_the_appellant_hears_the_outcome(status):
    account, case_id = _acct(), _acct()
    moderation_handlers.on_appeal_resolved(
        _env(
            "appeal.resolved",
            {
                "appeal_id": _acct(),
                "case_id": case_id,
                "target_type": "post",
                "status": status,
                "reversal": None,
                "account_id": account,
            },
        )
    )
    (row,) = Notification.objects.filter(kind="moderation.appeal")
    assert str(row.recipient_id) == account
    assert row.data["status"] == status
    assert registry.url_for(row) == f"/support?case={case_id}"


def test_an_old_appeal_event_without_the_appellant_is_skipped():
    moderation_handlers.on_appeal_resolved(
        _env("appeal.resolved", {"appeal_id": _acct(), "case_id": _acct(), "status": "upheld"})
    )
    assert not Notification.objects.exists()


def test_a_notice_reaches_each_recipient_with_its_text():
    a, b, notice_id = _acct(), _acct(), _acct()
    env = _env(
        "system.notice",
        {"notice_id": notice_id, "recipients": [a, b], "body": "تحديث مهم لصفحتك"},
    )
    moderation_handlers.on_system_notice(env)
    rows = Notification.objects.filter(kind="system.notice")
    assert {str(r.recipient_id) for r in rows} == {a, b}
    assert {r.body for r in rows} == {"تحديث مهم لصفحتك"}
    assert all(r.actor_id is None and r.category == "account" for r in rows)
    assert registry.url_for(rows[0]) == "/support?tab=notices"


def test_the_handlers_are_registered_and_the_kinds_described():
    assert moderation_handlers.on_moderation_decision in handlers_for("moderation.actioned")
    assert moderation_handlers.on_appeal_resolved in handlers_for("appeal.resolved")
    assert moderation_handlers.on_system_notice in handlers_for("system.notice")
    described = {k["kind"]: k["category"] for k in registry.describe()}
    assert described["moderation.decision"] == "account"
    assert described["system.notice"] == "account"
    assert "account" in registry.preference_keys()
