"""Chat API: DM/group, messages, voice, receipts, reactions, authz, block."""

import uuid

import pytest
from django.urls import reverse

from chat import services
from chat.models import BlockedPair, Conversation, OutboxEvent

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


# ---- conversations ----------------------------------------------------------


def test_dm_is_deduplicated(client_for):
    a, b = _acct(), _acct()
    r1 = client_for(a).post(
        reverse("chat:conversations"), {"type": "dm", "other_id": b}, format="json"
    )
    assert r1.status_code == 201
    r2 = client_for(b).post(
        reverse("chat:conversations"), {"type": "dm", "other_id": a}, format="json"
    )
    # Same canonical DM thread regardless of who initiates / direction.
    assert r1.json()["data"]["id"] == r2.json()["data"]["id"]
    assert Conversation.objects.filter(type="dm").count() == 1


def test_non_member_cannot_read_messages(client_for):
    a, b = _acct(), _acct()
    conv = services.create_or_get_dm(a, b)
    outsider = _acct()
    resp = client_for(outsider).get(reverse("chat:messages", args=[conv.id]))
    assert resp.status_code == 404  # not disclosed


def test_send_message_emits_event_with_recipients(client_for):
    a, b = _acct(), _acct()
    conv = services.create_or_get_dm(a, b)
    resp = client_for(a).post(
        reverse("chat:messages", args=[conv.id]), {"body": "hi there"}, format="json"
    )
    assert resp.status_code == 201
    assert OutboxEvent.objects.filter(event_type="message.created").exists()
    event = OutboxEvent.objects.get(event_type="message.created")
    # OutboxEvent.payload holds the full envelope; the event body is under "payload".
    assert set(event.payload["payload"]["recipients"]) == {a, b}


def test_voice_message(client_for):
    a, b = _acct(), _acct()
    conv = services.create_or_get_dm(a, b)
    media_id = str(uuid.uuid4())
    resp = client_for(a).post(
        reverse("chat:voice-messages", args=[conv.id]),
        {"media_id": media_id, "duration_ms": 4200},
        format="json",
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["type"] == "voice"
    assert data["attachments"][0]["kind"] == "voice"
    assert data["attachments"][0]["duration_ms"] == 4200


def test_blocked_user_cannot_dm(client_for):
    a, b = _acct(), _acct()
    BlockedPair.objects.create(blocker_id=b, blocked_id=a)  # b blocked a
    resp = client_for(a).post(
        reverse("chat:conversations"), {"type": "dm", "other_id": b}, format="json"
    )
    assert resp.status_code == 403


def test_group_create_and_send(client_for):
    a, b, c = _acct(), _acct(), _acct()
    create = client_for(a).post(
        reverse("chat:conversations"),
        {"type": "group", "member_ids": [b, c], "title": "Trip"},
        format="json",
    )
    assert create.status_code == 201
    conv_id = create.json()["data"]["id"]
    assert set(create.json()["data"]["members"]) == {a, b, c}
    msg = client_for(b).post(
        reverse("chat:messages", args=[conv_id]), {"body": "yo"}, format="json"
    )
    assert msg.status_code == 201


# ---- receipts + reactions ---------------------------------------------------


def test_mark_read_emits_event(client_for):
    a, b = _acct(), _acct()
    conv = services.create_or_get_dm(a, b)
    msg = services.send_message(a, str(conv.id), body="hello")
    resp = client_for(b).post(
        reverse("chat:read", args=[conv.id]), {"up_to_message_id": str(msg.id)}, format="json"
    )
    assert resp.status_code == 200
    assert OutboxEvent.objects.filter(event_type="message.read").exists()


def test_react_to_message(client_for):
    a, b = _acct(), _acct()
    conv = services.create_or_get_dm(a, b)
    msg = services.send_message(a, str(conv.id), body="hello")
    resp = client_for(b).post(
        reverse("chat:message-reactions", args=[msg.id]), {"type": "love"}, format="json"
    )
    assert resp.status_code == 200
    assert OutboxEvent.objects.filter(event_type="message.reacted").exists()


def test_outsider_cannot_react(client_for):
    a, b = _acct(), _acct()
    conv = services.create_or_get_dm(a, b)
    msg = services.send_message(a, str(conv.id), body="hello")
    resp = client_for(_acct()).post(
        reverse("chat:message-reactions", args=[msg.id]), {"type": "love"}, format="json"
    )
    assert resp.status_code == 404


# ---- marketplace contact -> conversation (cross-service event) -------------


def test_marketplace_contact_creates_conversation():
    from chat.handlers import on_marketplace_contact
    from chat.models import Conversation
    from tara_events.envelope import EventEnvelope

    buyer, seller, listing = _acct(), _acct(), str(uuid.uuid4())
    env = EventEnvelope(
        event_type="marketplace.contact.requested",
        subject_id=listing,
        producer="marketplace-service",
        payload={"buyer_id": buyer, "seller_id": seller, "listing_id": listing},
    )
    on_marketplace_contact(env)
    on_marketplace_contact(env)  # idempotent — reuses the same thread
    convs = Conversation.objects.filter(type="marketplace", listing_id=listing)
    assert convs.count() == 1
    assert set(services.member_ids(convs.first())) == {buyer, seller}
