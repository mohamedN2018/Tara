"""Inbox ordering, per-member read state, and query counts."""

import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from chat import services

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def test_inbox_sorts_by_latest_message_not_creation(client_for):
    me = _acct()
    old = services.create_or_get_dm(me, _acct())
    new = services.create_or_get_dm(me, _acct())
    empty = services.create_or_get_dm(me, _acct())  # no messages: sorts by creation
    services.send_message(me, str(new.id), body="first")
    services.send_message(me, str(old.id), body="latest")

    ids = [c["id"] for c in client_for(me).get(reverse("chat:conversations")).json()["data"]]
    assert ids == [str(old.id), str(new.id), str(empty.id)]


def test_inbox_cursor_walks_every_conversation_once(client_for):
    me = _acct()
    conversations = [services.create_or_get_dm(me, _acct()) for _ in range(5)]
    services.send_message(me, str(conversations[0].id), body="hi")
    client = client_for(me)

    seen, cursor = [], None
    for _ in range(6):
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = client.get(reverse("chat:conversations"), params).json()
        seen += [c["id"] for c in body["data"]]
        cursor = body["page"]["next_cursor"]
        if not cursor:
            break
    assert seen[0] == str(conversations[0].id)
    assert sorted(seen) == sorted(str(c.id) for c in conversations)


def test_member_read_state_survives_reload(client_for):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    message = services.send_message(me, str(conv.id), body="hi")
    services.mark_read(other, str(conv.id), str(message.id))

    data = client_for(me).get(reverse("chat:conversations")).json()["data"][0]
    states = {s["account_id"]: s for s in data["member_states"]}
    assert states[other]["last_read_message_id"] == str(message.id)
    assert states[me]["last_read_message_id"] is None
    assert sorted(data["members"]) == sorted([me, other])


def test_left_member_is_not_listed(client_for):
    me, other, third = _acct(), _acct(), _acct()
    conv = services.create_group(me, [other, third], "team")
    conv.members.filter(account_id=third).update(left_at=conv.created_at)
    data = client_for(me).get(reverse("chat:conversations")).json()["data"][0]
    assert sorted(data["members"]) == sorted([me, other])


def test_inbox_queries_do_not_grow_with_conversations(client_for):
    me = _acct()
    client = client_for(me)
    services.create_or_get_dm(me, _acct())
    with CaptureQueriesContext(connection) as few:
        client.get(reverse("chat:conversations"))
    for _ in range(6):
        services.create_or_get_dm(me, _acct())
    with CaptureQueriesContext(connection) as many:
        client.get(reverse("chat:conversations"))
    assert len(many) == len(few)


def test_message_queries_do_not_grow_with_messages(client_for):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    client = client_for(me)
    media = [{"media_id": str(uuid.uuid4()), "kind": "image"}]
    services.send_message(me, str(conv.id), attachments=media, message_type="image")
    url = reverse("chat:messages", args=[conv.id])
    with CaptureQueriesContext(connection) as few:
        client.get(url)
    for _ in range(6):
        services.send_message(me, str(conv.id), attachments=media, message_type="image")
    with CaptureQueriesContext(connection) as many:
        resp = client.get(url)
    assert len(many) == len(few)
    assert all(m["attachments"] for m in resp.json()["data"])
