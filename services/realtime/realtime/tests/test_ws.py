"""WebSocket gateway tests using the in-memory channel layer."""

import uuid

import pytest
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from realtime.groups import user_group
from realtime.routing import websocket_urlpatterns

pytestmark = pytest.mark.asyncio


def _app():
    return URLRouter(websocket_urlpatterns)


async def test_connect_rejected_without_token():
    comm = WebsocketCommunicator(_app(), "/ws/v1/")
    connected, _ = await comm.connect()
    assert connected is False


async def test_connect_rejected_with_bad_token():
    comm = WebsocketCommunicator(_app(), "/ws/v1/?token=not-a-jwt")
    connected, _ = await comm.connect()
    assert connected is False


async def test_connect_and_receive_push(token_for):
    account_id = str(uuid.uuid4())
    comm = WebsocketCommunicator(_app(), f"/ws/v1/?token={token_for(account_id)}")
    connected, _ = await comm.connect()
    assert connected is True
    hello = await comm.receive_json_from()
    assert hello["event"] == "connected"
    assert hello["account_id"] == account_id

    # The bridge pushes to the user's group; the socket should receive it.
    layer = get_channel_layer()
    await layer.group_send(
        user_group(account_id),
        {"type": "push", "data": {"event": "chat.message.created", "message_id": "m1"}},
    )
    pushed = await comm.receive_json_from()
    assert pushed["event"] == "chat.message.created"
    assert pushed["message_id"] == "m1"
    await comm.disconnect()


async def test_typing_broadcasts_between_subscribers(token_for):
    conv_id = str(uuid.uuid4())
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    comm_a = WebsocketCommunicator(_app(), f"/ws/v1/?token={token_for(a)}")
    comm_b = WebsocketCommunicator(_app(), f"/ws/v1/?token={token_for(b)}")
    assert (await comm_a.connect())[0]
    assert (await comm_b.connect())[0]
    await comm_a.receive_json_from()  # drain "connected"
    await comm_b.receive_json_from()

    await comm_a.send_json_to({"action": "subscribe", "conversation_id": conv_id})
    await comm_b.send_json_to({"action": "subscribe", "conversation_id": conv_id})
    await comm_a.send_json_to({"action": "typing", "conversation_id": conv_id})

    received = await comm_b.receive_json_from()
    assert received["event"] == "conversation.typing"
    assert received["actor_id"] == a
    assert received["conversation_id"] == conv_id
    await comm_a.disconnect()
    await comm_b.disconnect()


async def test_ping_pong(token_for):
    comm = WebsocketCommunicator(_app(), f"/ws/v1/?token={token_for(str(uuid.uuid4()))}")
    assert (await comm.connect())[0]
    await comm.receive_json_from()  # connected
    await comm.send_json_to({"action": "ping"})
    pong = await comm.receive_json_from()
    assert pong["event"] == "pong"
    await comm.disconnect()


def test_feed_summary_event_pushes_to_every_recipient(monkeypatch):
    from realtime import bridge
    from tara_events.envelope import EventEnvelope

    pushed = []
    monkeypatch.setattr(bridge, "_push_to_user", lambda who, data: pushed.append((who, data)))
    bridge.on_feed_item_added(
        EventEnvelope(
            event_type="feed.item.added",
            subject_id="p1",
            producer="feed-service",
            payload={"recipients": ["a", "b"], "post_id": "p1", "author_id": "z"},
        )
    )
    assert [who for who, _ in pushed] == ["a", "b"]
    assert pushed[0][1] == {"event": "feed.item.added", "post_id": "p1", "author_id": "z"}


def test_message_frame_tells_each_recipient_if_they_muted(monkeypatch):
    from realtime import bridge
    from tara_events.envelope import EventEnvelope

    pushed = {}
    monkeypatch.setattr(bridge, "_push_to_user", lambda who, data: pushed.update({who: data}))
    bridge.on_message_created(
        EventEnvelope(
            event_type="message.created",
            subject_id="m1",
            producer="chat-service",
            payload={"recipients": ["a", "b"], "muted": ["b"], "conversation_id": "c"},
        )
    )
    assert (pushed["a"]["muted"], pushed["b"]["muted"]) == (False, True)
