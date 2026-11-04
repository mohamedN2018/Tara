"""Hidden presence (plan 08 3C): the token's ``show_presence=false`` makes the
account read as offline, with no last-seen time, to every peer."""

import uuid

import pytest
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from realtime import presence
from realtime.routing import websocket_urlpatterns


def _acct() -> str:
    return str(uuid.uuid4())


async def _open(token):
    comm = WebsocketCommunicator(URLRouter(websocket_urlpatterns), f"/ws/v1/?token={token}")
    connected, _ = await comm.connect()
    assert connected
    assert (await comm.receive_json_from())["event"] == "connected"
    return comm


async def _next(comm, event, timeout=1):
    while True:
        frame = await comm.receive_json_from(timeout=timeout)
        if frame.get("event") == event:
            return frame


def test_hidden_flag_reads_offline_without_last_seen():
    store = presence.MemoryPresence()
    me = _acct()
    store.touch(me, "tab", 1000.0)
    assert store.state(me, 1001.0) == (True, None)
    assert store.set_hidden(me, True) is False
    assert store.state(me, 1001.0) == (False, None)
    assert store.set_hidden(me, False) is True
    assert store.state(me, 1001.0) == (True, None)


@pytest.mark.asyncio
async def test_hidden_account_is_never_announced_or_answered(token_for, audiences):
    me, friend = _acct(), _acct()
    audiences[me] = {friend}
    audiences[friend] = {me}
    watcher = await _open(token_for(friend))

    tab = await _open(token_for(me, show_presence=False))
    # An "offline" goes out (peers may have seen it online), never an "online".
    frame = await _next(watcher, "presence.changed")
    assert (frame["account_id"], frame["online"], frame["last_seen"]) == (me, False, None)
    assert presence.is_hidden(me) is True

    await watcher.send_json_to({"action": "presence.query", "account_ids": [me]})
    frame = await _next(watcher, "presence.state")
    assert frame["states"] == [{"account_id": me, "online": False, "last_seen": None}]

    # Reciprocal: with active status off, you don't see your friends either.
    await tab.send_json_to({"action": "presence.query", "account_ids": [friend]})
    frame = await _next(tab, "presence.state")
    assert frame["states"] == []

    await tab.disconnect()
    await watcher.disconnect()


@pytest.mark.asyncio
async def test_turning_it_back_on_announces_online(token_for, audiences):
    me, friend = _acct(), _acct()
    audiences[me] = {friend}
    audiences[friend] = {me}
    hidden_tab = await _open(token_for(me, show_presence=False))
    watcher = await _open(token_for(friend))

    visible_tab = await _open(token_for(me, show_presence=True))
    frame = await _next(watcher, "presence.changed")
    assert (frame["account_id"], frame["online"]) == (me, True)
    assert presence.is_hidden(me) is False
    assert presence.state(me)["online"] is True

    await visible_tab.disconnect()
    await hidden_tab.disconnect()
    await watcher.disconnect()


# ---- the current choice beats a stale token claim (fix track A) -------------------------


def _pref_event(account_id: str, show: bool, occurred_at: str = "2026-11-04T12:00:00+00:00"):
    from tara_events.envelope import EventEnvelope

    return EventEnvelope(
        event_type="account.presence.updated",
        subject_id=account_id,
        producer="identity-service",
        payload={"account_id": account_id, "show_presence": show},
        occurred_at=occurred_at,
    )


def test_preference_store_keeps_the_newest_choice():
    store = presence.MemoryPresence()
    me = _acct()
    assert store.preference(me) is None
    assert store.set_preference(me, False, 200.0) is True
    assert store.set_preference(me, True, 100.0) is False  # an older event
    assert store.preference(me) is False
    assert store.set_preference(me, True, 300.0) is True
    assert store.preference(me) is True


@pytest.mark.asyncio
async def test_stale_visible_token_cannot_unhide_after_turning_it_off(token_for, audiences):
    """A second tab reconnecting with an older token (show_presence=true) used to
    clear the hidden flag. The stored choice from identity now wins."""
    from asgiref.sync import sync_to_async

    from realtime import bridge

    me, friend = _acct(), _acct()
    audiences[me] = {friend}
    audiences[friend] = {me}
    watcher = await _open(token_for(friend))
    old_tab = await _open(token_for(me, show_presence=True))
    assert (await _next(watcher, "presence.changed"))["online"] is True

    # The owner turns it off in another tab: identity emits the event.
    await sync_to_async(bridge.on_presence_updated)(_pref_event(me, False))
    frame = await _next(watcher, "presence.changed")
    assert (frame["account_id"], frame["online"], frame["last_seen"]) == (me, False, None)
    assert presence.is_hidden(me) is True

    # The already-open tab follows at once: it no longer sees friends either.
    await old_tab.send_json_to({"action": "presence.query", "account_ids": [friend]})
    assert (await _next(old_tab, "presence.state"))["states"] == []

    # A reconnect with the stale token does not clear the flag.
    stale = await _open(token_for(me, show_presence=True))
    assert presence.is_hidden(me) is True
    await watcher.send_json_to({"action": "presence.query", "account_ids": [me]})
    frame = await _next(watcher, "presence.state")
    assert frame["states"] == [{"account_id": me, "online": False, "last_seen": None}]

    # An older, replayed event changes nothing.
    await sync_to_async(bridge.on_presence_updated)(
        _pref_event(me, True, occurred_at="2026-11-04T11:00:00+00:00")
    )
    assert presence.is_hidden(me) is True

    # Turning it back on shows the account again, without a new token.
    await sync_to_async(bridge.on_presence_updated)(
        _pref_event(me, True, occurred_at="2026-11-04T13:00:00+00:00")
    )
    frame = await _next(watcher, "presence.changed")
    assert (frame["account_id"], frame["online"]) == (me, True)
    assert presence.is_hidden(me) is False

    for comm in (stale, old_tab, watcher):
        await comm.disconnect()


@pytest.mark.asyncio
async def test_stored_choice_also_beats_a_stale_hidden_claim(token_for, audiences):
    from asgiref.sync import sync_to_async

    from realtime import bridge

    me = _acct()
    await sync_to_async(bridge.on_presence_updated)(_pref_event(me, True))
    tab = await _open(token_for(me, show_presence=False))
    assert presence.is_hidden(me) is False
    await tab.disconnect()
