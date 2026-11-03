"""WebSocket gateway tests using the in-memory channel layer."""

import asyncio
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
    await asyncio.sleep(0.05)  # subscriptions on different sockets complete concurrently
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


def test_notification_read_and_deleted_frames_reach_only_the_recipient(monkeypatch):
    from realtime import bridge
    from tara_events.envelope import EventEnvelope

    pushed = []
    monkeypatch.setattr(bridge, "_push_to_user", lambda who, data: pushed.append((who, data)))
    bridge.on_notification_read(
        EventEnvelope(
            event_type="notification.read",
            subject_id="u1",
            producer="notification-service",
            payload={"recipient": "u1", "notification_ids": ["n1", "n2"], "all": False},
        )
    )
    bridge.on_notification_deleted(
        EventEnvelope(
            event_type="notification.deleted",
            subject_id="u1",
            producer="notification-service",
            payload={"recipient": "u1", "notification_ids": ["n3"]},
        )
    )
    bridge.on_notification_deleted(  # nothing to delete: no frame
        EventEnvelope(
            event_type="notification.deleted",
            subject_id="u1",
            producer="notification-service",
            payload={"recipient": "u1", "notification_ids": []},
        )
    )
    assert pushed == [
        ("u1", {"event": "notification.read", "notification_ids": ["n1", "n2"], "all": False}),
        ("u1", {"event": "notification.deleted", "notification_ids": ["n3"]}),
    ]


# ---- hardening (review) --------------------------------------------------------


async def _open(account_id, token_for, **kwargs):
    comm = WebsocketCommunicator(_app(), f"/ws/v1/?token={token_for(account_id)}", **kwargs)
    assert (await comm.connect())[0]
    assert (await comm.receive_json_from())["event"] == "connected"
    return comm


async def test_typing_is_not_echoed_to_the_typists_own_tabs(token_for):
    conv_id = str(uuid.uuid4())
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    a1, a2, b1 = [await _open(x, token_for) for x in (a, a, b)]
    for comm in (a1, a2, b1):
        await comm.send_json_to({"action": "subscribe", "conversation_id": conv_id})
    await asyncio.sleep(0.05)
    await a1.send_json_to({"action": "typing", "conversation_id": conv_id})
    assert (await b1.receive_json_from())["actor_id"] == a
    assert await a1.receive_nothing(timeout=0.2)
    assert await a2.receive_nothing(timeout=0.2)
    for comm in (a1, a2, b1):
        await comm.disconnect()


async def test_revoked_member_stops_receiving_typing(token_for):
    from asgiref.sync import sync_to_async

    from realtime import bridge
    from tara_events.envelope import EventEnvelope

    conv_id = str(uuid.uuid4())
    a, removed = str(uuid.uuid4()), str(uuid.uuid4())
    comm_a, comm_removed = await _open(a, token_for), await _open(removed, token_for)
    for comm in (comm_a, comm_removed):
        await comm.send_json_to({"action": "subscribe", "conversation_id": conv_id})
    await asyncio.sleep(0.05)
    await sync_to_async(bridge.on_conversation_changed)(
        EventEnvelope(
            event_type="conversation.member.changed",
            subject_id=conv_id,
            producer="chat-service",
            payload={
                "conversation_id": conv_id,
                "action": "removed",
                "recipients": [a, removed],
                "revoked": [removed],
            },
        )
    )
    assert (await comm_removed.receive_json_from())["event"] == "chat.conversation.changed"
    assert (await comm_a.receive_json_from())["event"] == "chat.conversation.changed"
    await comm_a.send_json_to({"action": "typing", "conversation_id": conv_id})
    assert await comm_removed.receive_nothing(timeout=0.2)
    await comm_a.disconnect()
    await comm_removed.disconnect()


async def test_oversized_frames_close_and_junk_frames_are_ignored(token_for):
    comm = await _open(str(uuid.uuid4()), token_for)
    await comm.send_to(text_data="{not json")
    await comm.send_to(bytes_data=b"\x00\x01")
    await comm.send_json_to({"action": "subscribe", "conversation_id": "../internal"})
    await comm.send_json_to({"action": "ping"})
    assert (await comm.receive_json_from())["event"] == "pong"  # still alive
    await comm.send_to(text_data="x" * 20_000)
    assert await comm.receive_output() == {"type": "websocket.close", "code": 1009}


async def test_a_socket_that_floods_is_rate_limited(token_for, settings):
    settings.WS_FRAME_BURST = 5
    settings.WS_FRAMES_PER_SECOND = 0.001
    comm = await _open(str(uuid.uuid4()), token_for)
    for _ in range(20):
        await comm.send_json_to({"action": "ping"})
    pongs = 0
    while not await comm.receive_nothing(timeout=0.2):
        pongs += (await comm.receive_json_from())["event"] == "pong"
    assert pongs == 5
    await comm.disconnect()


async def test_a_slow_dependency_does_not_stall_other_sockets(token_for, monkeypatch):
    import time

    def slow_member(conversation_id, account_id):
        time.sleep(1.0)
        return True

    monkeypatch.setattr("realtime.chat_client.is_member", slow_member)
    slow, other = (
        await _open(str(uuid.uuid4()), token_for),
        await _open(str(uuid.uuid4()), token_for),
    )
    await slow.send_json_to({"action": "subscribe", "conversation_id": str(uuid.uuid4())})
    await asyncio.sleep(0.05)
    started = time.monotonic()
    await other.send_json_to({"action": "ping"})
    assert (await other.receive_json_from(timeout=0.8))["event"] == "pong"
    assert time.monotonic() - started < 0.8
    await asyncio.sleep(1.0)
    await slow.disconnect()
    await other.disconnect()


async def test_token_in_the_subprotocol_header_is_echoed_back(token_for):
    account_id = str(uuid.uuid4())
    token = token_for(account_id)
    comm = WebsocketCommunicator(_app(), "/ws/v1/", subprotocols=[token])
    connected, subprotocol = await comm.connect()
    assert connected is True and subprotocol == token
    assert (await comm.receive_json_from())["account_id"] == account_id
    await comm.disconnect()
