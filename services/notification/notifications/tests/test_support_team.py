"""A member's message to Tara Support reaches the support team (fix round 3):
``message.support``, one row per thread, opening the support inbox on it."""

import uuid

import pytest
from django.urls import reverse

from notifications import registry
from notifications.handlers import on_message_created, on_message_deleted
from notifications.models import Notification
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _deliver(conversation, sender, message_id, preview, recipients):
    on_message_created(
        EventEnvelope(
            event_type="message.created",
            subject_id=message_id,
            producer="chat-service",
            payload={
                "conversation_id": conversation,
                "message_id": message_id,
                "sender": sender,
                "type": "text",
                "recipients": [sender],
                "muted": [],
                "preview": preview,
                "team": {"kind": "support", "page_id": None, "name": "", "recipients": recipients},
            },
        )
    )


def test_a_support_message_notifies_the_support_team_once_per_thread(client_for):
    member, mod, admin = _acct(), _acct(), _acct()
    conversation = str(uuid.uuid4())
    _deliver(conversation, member, str(uuid.uuid4()), "My account is locked", [mod, admin, member])
    _deliver(conversation, member, str(uuid.uuid4()), "Please help", [mod, admin, member])
    assert not Notification.objects.filter(recipient_id=member).exists()  # never yourself
    for staff in (mod, admin):
        row = Notification.objects.get(recipient_id=staff)
        assert row.kind == "message.support" and row.category == "messages"
        assert str(row.actor_id) == member and row.body == "Please help"
        assert row.data["conversation_id"] == conversation
    item = client_for(mod, roles=["moderator"]).get(reverse("notifications:list")).json()["data"][0]
    assert item["url"] == f"/admin/support?conversation={conversation}"
    assert item["kind"] == "message.support"


def test_a_deleted_support_message_takes_its_notice_with_it():
    member, mod = _acct(), _acct()
    conversation, message_id = str(uuid.uuid4()), str(uuid.uuid4())
    _deliver(conversation, member, message_id, "oops", [mod])
    assert Notification.objects.filter(recipient_id=mod, kind="message.support").exists()
    on_message_deleted(
        EventEnvelope(
            event_type="message.deleted",
            subject_id=message_id,
            producer="chat-service",
            payload={"conversation_id": conversation, "message_id": message_id},
        )
    )
    assert not Notification.objects.filter(recipient_id=mod).exists()


def test_only_staff_see_the_support_toggle_in_settings(client_for):
    member = client_for(_acct()).get(reverse("notifications:kinds")).json()["data"]["kinds"]
    staff = (client_for(_acct(), roles=["moderator"]).get(reverse("notifications:kinds")).json())[
        "data"
    ]["kinds"]
    assert "message.support" not in {k["kind"] for k in member}
    assert "message.support" in {k["kind"] for k in staff}
    assert "message.support" not in {k["kind"] for k in registry.describe()}
    assert "message.support" in {k["kind"] for k in registry.describe({"moderation.case.view"})}
