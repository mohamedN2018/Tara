"""Presence: multi-tab ref counting, heartbeat TTL, last_seen, peer-only delivery."""

import asyncio
import os
import uuid

import pytest
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from realtime import bridge, presence
from realtime.peers import audience as real_audience
from realtime.routing import websocket_urlpatterns
from tara_events.envelope import EventEnvelope


def _app():
    return URLRouter(websocket_urlpatterns)


def _acct() -> str:
    return str(uuid.uuid4())


async def _open(token_for, account_id):
    comm = WebsocketCommunicator(_app(), f"/ws/v1/?token={token_for(account_id)}")
    connected, _ = await comm.connect()
    assert connected
    assert (await comm.receive_json_from())["event"] == "connected"
    return comm


async def _next(comm, event, timeout=1):
    """The next frame with this ``event`` (others, like pongs, are skipped)."""
    while True:
        frame = await comm.receive_json_from(timeout=timeout)
        if frame.get("event") == event:
            return frame


# ---- the store ------------------------------------------------------------------


def _stores():
    stores = [presence.MemoryPresence()]
    url = os.getenv("REDIS_URL", "")
    if url:
        try:
            redis_store = presence.RedisPresence(url)
            redis_store.redis.ping()
            stores.append(redis_store)
        except Exception:  # noqa: BLE001,S110 - no Redis here: memory only
            pass
    return stores


@pytest.mark.parametrize("store", _stores(), ids=lambda s: type(s).__name__)
def test_last_tab_decides(store):
    account = _acct()
    assert store.touch(account, "tab-1", 1000.0) is True  # first socket: came online
    assert store.touch(account, "tab-2", 1001.0) is False
    assert store.drop(account, "tab-1", 1002.0) is False  # one tab left: still online
    assert store.state(account, 1003.0) == (True, None)
    assert store.drop(account, "tab-2", 1004.0) is True  # last one out
    online, last_seen = store.state(account, 1005.0)
    assert online is False and last_seen == 1004.0
    if isinstance(store, presence.RedisPresence):
        store.redis.delete(f"presence:sock:{account}", f"presence:last_seen:{account}")


@pytest.mark.parametrize("store", _stores(), ids=lambda s: type(s).__name__)
def test_heartbeats_keep_a_socket_online_and_silence_expires_it(store, settings):
    account = _acct()
    ttl = settings.PRESENCE_TTL
    store.touch(account, "tab", 1000.0)
    for minute in range(1, 6):  # a socket that only pings, for five minutes
        assert store.touch(account, "tab", 1000.0 + minute * 30) is False
    assert store.state(account, 1150.0 + ttl - 1)[0] is True
    # A crashed tab never says goodbye: it ages out, last_seen is its last heartbeat.
    assert store.state(account, 1150.0 + ttl + 1) == (False, 1150.0)
    # Coming back after that is a fresh "online".
    assert store.touch(account, "tab-new", 1150.0 + ttl + 2) is True


# ---- the socket ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_tabs_close_one_still_online_close_both_offline(token_for, audiences):
    me, peer = _acct(), _acct()
    audiences[me] = {peer}
    audiences[peer] = {me}
    watcher = await _open(token_for, peer)

    tab1 = await _open(token_for, me)
    frame = await _next(watcher, "presence.changed")
    assert (frame["account_id"], frame["online"]) == (me, True)
    tab2 = await _open(token_for, me)

    await tab1.disconnect()
    assert presence.is_online(me) is True
    assert await watcher.receive_nothing(timeout=0.2)  # no flap

    await tab2.disconnect()
    frame = await _next(watcher, "presence.changed")
    assert frame["online"] is False and frame["last_seen"]
    assert presence.is_online(me) is False
    await watcher.disconnect()


@pytest.mark.asyncio
async def test_presence_is_never_sent_to_strangers(token_for, audiences):
    me, stranger = _acct(), _acct()
    audiences[me] = set()
    watcher = await _open(token_for, stranger)
    tab = await _open(token_for, me)
    await tab.disconnect()
    assert await watcher.receive_nothing(timeout=0.3)
    await watcher.disconnect()


@pytest.mark.asyncio
async def test_presence_query_answers_only_for_allowed_peers(token_for, audiences):
    me, friend, stranger = _acct(), _acct(), _acct()
    audiences[me] = {friend}
    friend_tab = await _open(token_for, friend)
    stranger_tab = await _open(token_for, stranger)
    mine = await _open(token_for, me)

    await mine.send_json_to({"action": "presence.query", "account_ids": [friend, stranger]})
    frame = await _next(mine, "presence.state")
    assert frame["states"] == [{"account_id": friend, "online": True, "last_seen": None}]

    await friend_tab.disconnect()
    await mine.send_json_to({"action": "presence.query", "account_ids": [friend]})
    frame = await _next(mine, "presence.state")
    assert frame["states"][0]["online"] is False and frame["states"][0]["last_seen"]
    await mine.send_json_to({"action": "presence.query", "account_ids": "not-a-list"})
    assert await mine.receive_nothing(timeout=0.2)
    await stranger_tab.disconnect()
    await mine.disconnect()


@pytest.mark.asyncio
async def test_ping_is_a_heartbeat(token_for, monkeypatch):
    me = _acct()
    seen = []
    real = presence.heartbeat
    monkeypatch.setattr(presence, "heartbeat", lambda a, c: seen.append(a) or real(a, c))
    tab = await _open(token_for, me)
    await tab.send_json_to({"action": "ping"})
    assert (await tab.receive_json_from())["event"] == "pong"
    assert seen == [me]
    await tab.disconnect()


@pytest.mark.asyncio
async def test_typing_is_throttled_per_conversation(token_for):
    conv = _acct()
    a, b = _acct(), _acct()
    tab_a = await _open(token_for, a)
    tab_b = await _open(token_for, b)
    for tab in (tab_a, tab_b):
        await tab.send_json_to({"action": "subscribe", "conversation_id": conv})
    await asyncio.sleep(0.05)
    await tab_a.send_json_to({"action": "typing", "conversation_id": conv})
    await tab_a.send_json_to({"action": "typing", "conversation_id": conv})
    assert (await _next(tab_b, "conversation.typing"))["actor_id"] == a
    assert await tab_b.receive_nothing(timeout=0.2)
    await tab_a.disconnect()
    await tab_b.disconnect()


# ---- audience ------------------------------------------------------------------


def test_audience_is_dm_peers_plus_friends_and_cached(monkeypatch):
    me, dm_peer, friend = _acct(), _acct(), _acct()
    calls = []
    monkeypatch.setattr(
        "realtime.chat_client.presence_peers", lambda a: calls.append("chat") or [dm_peer, me]
    )
    monkeypatch.setattr(
        "realtime.graph_client.friends", lambda a: calls.append("graph") or [friend]
    )
    assert real_audience(me) == {dm_peer, friend}
    assert real_audience(me) == {dm_peer, friend}
    assert calls == ["chat", "graph"]  # second answer came from the cache


def test_audience_fails_closed_and_is_not_cached(monkeypatch):
    me, dm_peer = _acct(), _acct()
    monkeypatch.setattr("realtime.chat_client.presence_peers", lambda a: [dm_peer])
    monkeypatch.setattr("realtime.graph_client.friends", lambda a: None)  # graph down
    assert real_audience(me) == {dm_peer}
    monkeypatch.setattr("realtime.chat_client.presence_peers", lambda a: None)
    assert real_audience(me) == set()


def test_block_hides_presence_both_ways(monkeypatch):
    pushed, dropped = [], []
    monkeypatch.setattr(bridge, "_push_to_user", lambda who, data: pushed.append((who, data)))
    monkeypatch.setattr("realtime.peers.invalidate", lambda *a: dropped.extend(a))
    bridge.on_user_blocked(
        EventEnvelope(
            event_type="user.blocked",
            subject_id="x",
            producer="graph-service",
            payload={"blocker_id": "a", "blocked_id": "b"},
        )
    )
    assert sorted(dropped) == ["a", "b"]
    assert {(who, d["account_id"], d["online"]) for who, d in pushed} == {
        ("a", "b", False),
        ("b", "a", False),
    }


def _event(event_type, payload):
    return EventEnvelope(
        event_type=event_type, subject_id="s", producer="chat-service", payload=payload
    )


def test_lifecycle_and_receipt_frames_reach_only_recipients(monkeypatch):
    pushed = []
    monkeypatch.setattr(bridge, "_push_to_user", lambda who, data: pushed.append((who, data)))
    bridge.on_message_edited(
        _event("message.edited", {"recipients": ["a"], "conversation_id": "c", "message_id": "m"})
    )
    bridge.on_message_deleted(
        _event(
            "message.deleted",
            {
                "recipients": ["a", "b"],
                "conversation_id": "c",
                "message_id": "m",
                "scope": "everyone",
            },
        )
    )
    bridge.on_message_delivered(
        _event(
            "message.delivered",
            {"recipients": ["b"], "conversation_id": "c", "account": "a", "up_to_seq": 4},
        )
    )
    assert [(who, d["event"]) for who, d in pushed] == [
        ("a", "chat.message.edited"),
        ("a", "chat.message.deleted"),
        ("b", "chat.message.deleted"),
        ("b", "chat.message.delivered"),
    ]
    assert pushed[-1][1]["up_to_seq"] == 4


def test_a_block_outlives_chats_stale_answer(monkeypatch):
    me, blocked, friend = _acct(), _acct(), _acct()
    # Chat has not processed the block yet: it still lists the DM peer.
    monkeypatch.setattr("realtime.chat_client.presence_peers", lambda a: [blocked, friend])
    monkeypatch.setattr("realtime.graph_client.friends", lambda a: [])
    monkeypatch.setattr(bridge, "_push_to_user", lambda who, data: None)
    assert real_audience(me) == {blocked, friend}  # cached before the block
    bridge.on_user_blocked(
        EventEnvelope(
            event_type="user.blocked",
            subject_id="x",
            producer="graph-service",
            payload={"blocker_id": blocked, "blocked_id": me},
        )
    )
    assert real_audience(me) == {friend}
    assert real_audience(me) == {friend}  # and the recomputed, cached answer too
    bridge.on_user_unblocked(
        EventEnvelope(
            event_type="user.unblocked",
            subject_id="x",
            producer="graph-service",
            payload={"blocker_id": blocked, "blocked_id": me},
        )
    )
    assert real_audience(me) == {blocked, friend}
