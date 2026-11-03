"""Call frames (roadmap 3.7): ringing reaches every callee device; answer, decline,
end and missed reach the audience the event names, with ids only."""

import uuid

import pytest
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from realtime import bridge
from realtime.routing import websocket_urlpatterns
from tara_events.envelope import EventEnvelope


def _id() -> str:
    return str(uuid.uuid4())


def _event(event_type: str, **payload) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        payload=payload,
        subject_id=payload.get("call_id", ""),
        producer="chat",
    )


@pytest.fixture
def pushed(monkeypatch):
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(bridge, "_push_to_user", lambda who, data: sent.append((who, data)))
    return sent


def test_started_rings_callees_and_tells_the_callers_other_devices(pushed):
    caller, x, y, call, conv = _id(), _id(), _id(), _id(), _id()
    bridge.on_call_started(
        _event(
            "call.started",
            call_id=call,
            conversation_id=conv,
            conversation_type="group",
            kind="video",
            initiator=caller,
            recipients=[x, y],
            ring_expires_at="2026-11-03T20:00:45+00:00",
        )
    )
    ringing = {who: data for who, data in pushed if data["event"] == "call.ringing"}
    assert set(ringing) == {x, y}
    assert ringing[x] == {
        "event": "call.ringing",
        "call_id": call,
        "conversation_id": conv,
        "conversation_type": "group",
        "kind": "video",
        "initiator": caller,
        "expires_at": "2026-11-03T20:00:45+00:00",
    }
    assert (
        caller,
        {"event": "call.updated", "call_id": call, "conversation_id": conv, "state": "ringing"},
    ) in pushed
    assert all(who != caller for who, data in pushed if data["event"] == "call.ringing")


@pytest.mark.parametrize("event_type", ["call.answered", "call.declined"])
def test_answer_and_decline_reach_every_member_with_who_did_it(pushed, event_type):
    a, b, call, conv = _id(), _id(), _id(), _id()
    handler = bridge.on_call_answered if event_type == "call.answered" else bridge.on_call_declined
    handler(_event(event_type, call_id=call, conversation_id=conv, account=b, recipients=[a, b]))
    assert [who for who, _ in pushed] == [a, b]
    assert pushed[0][1] == {
        "event": event_type,
        "call_id": call,
        "conversation_id": conv,
        "account": b,
    }


def test_ended_and_missed_frames_carry_no_free_text(pushed):
    a, b, call, conv = _id(), _id(), _id(), _id()
    bridge.on_call_ended(
        _event(
            "call.ended",
            call_id=call,
            conversation_id=conv,
            reason="hangup",
            duration_s=192,
            ringing=[],
            recipients=[a, b],
        )
    )
    bridge.on_call_missed(
        _event(
            "call.missed",
            call_id=call,
            conversation_id=conv,
            missed=[b],
            final=True,
            reason="timeout",
            recipients=[a, b],
        )
    )
    ended = [d for _, d in pushed if d["event"] == "call.ended"]
    missed = [d for _, d in pushed if d["event"] == "call.missed"]
    assert len(ended) == 2 and ended[0]["reason"] == "hangup" and ended[0]["duration_s"] == 192
    assert len(missed) == 2 and missed[0] == {
        "event": "call.missed",
        "call_id": call,
        "conversation_id": conv,
        "final": True,
        "missed": [b],
    }


@pytest.mark.asyncio
async def test_every_tab_of_the_callee_rings(token_for):
    from asgiref.sync import sync_to_async

    callee = _id()
    tabs = []
    for _ in range(2):
        comm = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), f"/ws/v1/?token={token_for(callee)}"
        )
        connected, _ = await comm.connect()
        assert connected
        tabs.append(comm)
    await sync_to_async(bridge.on_call_started)(
        _event(
            "call.started",
            call_id=_id(),
            conversation_id=_id(),
            conversation_type="dm",
            kind="audio",
            initiator=_id(),
            recipients=[callee],
        )
    )
    for comm in tabs:
        events = []
        while "call.ringing" not in events:
            events.append((await comm.receive_json_from(timeout=2))["event"])
        assert events[0] == "connected"
        await comm.disconnect()
