"""Calls (roadmap 3.7): a push-only ring path with no in-app rows, a clear push
with the same tag on answer or end, and an in-app row for a missed call."""

import base64
import json
import os
import uuid
from unittest import mock

import http_ece
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02

from notifications import handlers, push, registry, services
from notifications.models import Notification, NotificationPreference, PushDeviceToken
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

ENDPOINT = "https://fcm.googleapis.com/fcm/send/call"


def _acct() -> str:
    return str(uuid.uuid4())


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture
def vapid(settings):
    key = Vapid02()
    key.generate_keys()
    settings.VAPID_PRIVATE_KEY = _b64(
        key.private_key.private_numbers().private_value.to_bytes(32, "big")
    )
    settings.VAPID_PUBLIC_KEY = _b64(
        key.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    return settings


def _event(event_type: str, **payload) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type, payload=payload, subject_id=payload["call_id"], producer="chat"
    )


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    """Run a handler and commit; returns (recipient, data) of every call push queued."""
    sent: list[tuple[str, dict]] = []

    def _run(handler, event: EventEnvelope) -> list[tuple[str, dict]]:
        with (
            mock.patch(
                "notifications.tasks.deliver_call_push.delay",
                side_effect=lambda who, data: sent.append((who, data)),
            ),
            django_capture_on_commit_callbacks(execute=True),
        ):
            handler(event)
        return sent

    return _run


def _ids():
    return str(uuid.uuid4()), str(uuid.uuid4())


def test_the_kinds_are_registered():
    assert registry.get("call").in_app is False and registry.get("call").push is True
    assert registry.get("call.missed").in_app is True and registry.get("call.missed").push is False
    assert {"call", "call.missed"} <= {k["kind"] for k in registry.describe()}


def test_a_ring_is_push_only_for_every_callee(run):
    caller, x, y = _acct(), _acct(), _acct()
    call_id, conv = _ids()
    queued = run(
        handlers.on_call_started,
        _event(
            "call.started",
            call_id=call_id,
            conversation_id=conv,
            kind="video",
            initiator=caller,
            recipients=[x, y],
        ),
    )
    assert [who for who, _ in queued] == [x, y]
    assert queued[0][1] == {
        "kind": "call.ring",
        "tag": f"call:{call_id}",
        "call_id": call_id,
        "conversation_id": conv,
        "url": f"/messages/{conv}",
        "call_kind": "video",
        "body": "",
    }
    assert not Notification.objects.exists()  # no in-app row spam


def test_answer_and_decline_clear_the_ring_on_that_persons_devices(run):
    a, b = _acct(), _acct()
    call_id, conv = _ids()
    run(
        handlers.on_call_answered,
        _event(
            "call.answered", call_id=call_id, conversation_id=conv, account=b, recipients=[a, b]
        ),
    )
    queued = run(
        handlers.on_call_declined,
        _event(
            "call.declined", call_id=call_id, conversation_id=conv, account=a, recipients=[a, b]
        ),
    )
    assert [(who, d["kind"], d["reason"], d["tag"]) for who, d in queued] == [
        (b, "call.clear", "answered", f"call:{call_id}"),
        (a, "call.clear", "declined", f"call:{call_id}"),
    ]


def test_an_ended_call_clears_only_those_still_ringing(run):
    a, b, c = _acct(), _acct(), _acct()
    call_id, conv = _ids()
    queued = run(
        handlers.on_call_ended,
        _event(
            "call.ended",
            call_id=call_id,
            conversation_id=conv,
            reason="hangup",
            duration_s=10,
            ringing=[c],
            recipients=[a, b, c],
        ),
    )
    assert [(who, d["kind"]) for who, d in queued] == [(c, "call.clear")]


def test_a_missed_call_is_an_in_app_row_and_replaces_the_ring(run):
    caller, callee = _acct(), _acct()
    call_id, conv = _ids()
    queued = run(
        handlers.on_call_missed,
        _event(
            "call.missed",
            call_id=call_id,
            conversation_id=conv,
            kind="audio",
            initiator=caller,
            missed=[callee],
            final=True,
            reason="timeout",
            recipients=[caller, callee],
        ),
    )
    row = Notification.objects.get(recipient_id=callee)
    assert row.kind == "call.missed" and row.category == "messages"
    assert row.data == {"conversation_id": conv, "call_id": call_id, "call_kind": "audio"}
    assert str(row.actor_id) == caller
    assert registry.url_for(row) == f"/messages/{conv}"
    assert not Notification.objects.filter(recipient_id=caller).exists()
    # The row's own push is off by default; the replacement goes by the call tag.
    assert [(who, d["kind"], d["tag"]) for who, d in queued] == [
        (callee, "call.missed", f"call:{call_id}")
    ]


def test_call_log_messages_do_not_notify_as_messages():
    sender, recipient = _acct(), _acct()
    handlers.on_message_created(
        EventEnvelope(
            event_type="message.created",
            payload={
                "conversation_id": str(uuid.uuid4()),
                "message_id": str(uuid.uuid4()),
                "sender": sender,
                "type": "system",
                "recipients": [sender, recipient],
                "muted": [],
                "preview": "call:missed:audio",
            },
            subject_id="m",
            producer="chat",
        )
    )
    assert not Notification.objects.exists()


def _subscribe(account):
    receiver = ec.generate_private_key(ec.SECP256R1())
    public = receiver.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = os.urandom(16)
    PushDeviceToken.objects.create(
        account_id=account,
        platform="web",
        token=services.endpoint_token(ENDPOINT),
        subscription={"endpoint": ENDPOINT, "keys": {"p256dh": _b64(public), "auth": _b64(auth)}},
    )
    return receiver, auth


def test_a_ring_push_is_short_lived_urgent_and_tagged(vapid):
    account = _acct()
    receiver, auth = _subscribe(account)
    data = {"kind": "call.ring", "tag": "call:abc", "call_id": "abc", "url": "/messages/x"}
    with mock.patch("requests.post") as http:
        http.return_value = mock.Mock(status_code=201, text="")
        assert push.deliver_call(account, data) == "sent"
    sent = http.call_args.kwargs
    assert sent["headers"]["ttl"] == str(push.CALL_TTL_SECONDS)
    assert sent["headers"]["Urgency"] == "high"
    plain = http_ece.decrypt(
        sent["data"], private_key=receiver, auth_secret=auth, version="aes128gcm"
    )
    assert json.loads(plain) == data
    assert not Notification.objects.exists()


def test_ring_push_respects_the_call_setting_quiet_hours_and_missing_keys(vapid, settings):
    account = _acct()
    _subscribe(account)
    data = {"kind": "call.ring", "tag": "call:abc"}
    NotificationPreference.objects.create(account_id=account, prefs={"call": {"push": False}})
    with mock.patch("notifications.push.webpush") as send:
        assert push.deliver_call(account, data) == "muted"
        NotificationPreference.objects.filter(account_id=account).update(prefs={})
        with mock.patch("notifications.push.in_quiet_hours", return_value=True):
            assert push.deliver_call(account, data) == "quiet"
        assert push.deliver_call(_acct(), data) == "no_subscribers"
        settings.VAPID_PRIVATE_KEY = ""
        assert push.deliver_call(account, data) == "disabled"
    send.assert_not_called()
