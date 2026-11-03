"""Inbox ordering, per-member read state, and query counts."""

import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from chat import services
from chat.models import BlockedPair, OutboxEvent

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


# ---- reactions, mute, pin ----------------------------------------------------


def test_reactions_are_listed_and_removable(client_for):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    message = services.send_message(me, str(conv.id), body="hi")
    url = reverse("chat:message-reactions", args=[message.id])
    client = client_for(other)
    assert client.post(url, {"type": "love"}, format="json").status_code == 200
    assert client.post(url, {"type": "haha"}, format="json").status_code == 200  # replaces

    data = client_for(me).get(reverse("chat:messages", args=[conv.id])).json()["data"][0]
    assert data["reactions"] == [{"account_id": other, "type": "haha"}]

    assert client.delete(url).status_code == 204
    assert not message.reactions.exists()
    last = OutboxEvent.objects.filter(event_type="message.reacted").order_by("-created_at")[0]
    assert last.payload["payload"]["type"] is None


def test_outsider_cannot_react_or_unreact(client_for):
    conv = services.create_or_get_dm(_acct(), _acct())
    message = services.send_message(str(conv.created_by), str(conv.id), body="hi")
    url = reverse("chat:message-reactions", args=[message.id])
    assert client_for(_acct()).post(url, {"type": "love"}, format="json").status_code == 404
    assert client_for(_acct()).delete(url).status_code == 404


def test_blocked_peer_cannot_react(client_for):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    message = services.send_message(me, str(conv.id), body="hi")
    BlockedPair.objects.create(blocker_id=me, blocked_id=other)
    url = reverse("chat:message-reactions", args=[message.id])
    assert client_for(other).post(url, {"type": "love"}, format="json").status_code == 403


def test_mute_state_is_per_member_and_marks_the_event(client_for):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    url = reverse("chat:mute", args=[conv.id])
    assert client_for(me).post(url, {"minutes": 60}, format="json").status_code == 200

    mine = client_for(me).get(reverse("chat:conversation", args=[conv.id])).json()["data"]
    theirs = client_for(other).get(reverse("chat:conversation", args=[conv.id])).json()["data"]
    assert mine["muted_until"] is not None
    assert theirs["muted_until"] is None

    services.send_message(other, str(conv.id), body="hi")
    event = OutboxEvent.objects.get(event_type="message.created")
    assert event.payload["payload"]["muted"] == [me]

    assert client_for(me).post(url, {"minutes": 0}, format="json").status_code == 200
    mine = client_for(me).get(reverse("chat:conversation", args=[conv.id])).json()["data"]
    assert mine["muted_until"] is None


def test_pin_and_unpin_show_on_the_conversation(client_for):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    message = services.send_message(me, str(conv.id), body="remember this")
    url = reverse("chat:pin", args=[conv.id])
    client = client_for(other)
    assert client.post(url, {"message_id": str(message.id)}, format="json").status_code == 201
    assert client.post(url, {"message_id": str(message.id)}, format="json").status_code == 409

    data = client_for(me).get(reverse("chat:conversations")).json()["data"][0]
    assert data["pinned_messages"][0]["id"] == str(message.id)
    assert data["pinned_messages"][0]["body"] == "remember this"

    assert client.delete(url, {"message_id": str(message.id)}, format="json").status_code == 204
    data = client_for(me).get(reverse("chat:conversations")).json()["data"][0]
    assert data["pinned_messages"] == []


def test_cannot_pin_a_message_from_another_conversation(client_for):
    me = _acct()
    conv = services.create_or_get_dm(me, _acct())
    elsewhere = services.create_or_get_dm(_acct(), _acct())
    message = services.send_message(str(elsewhere.created_by), str(elsewhere.id), body="x")
    resp = client_for(me).post(
        reverse("chat:pin", args=[conv.id]), {"message_id": str(message.id)}, format="json"
    )
    assert resp.status_code == 404


# ---- groups ------------------------------------------------------------------


def _group(client, others, title="team"):
    resp = client.post(
        reverse("chat:conversations"),
        {"type": "group", "title": title, "member_ids": others},
        format="json",
    )
    assert resp.status_code == 201
    return resp.json()["data"]


def test_group_create_needs_another_member(client_for):
    me = _acct()
    resp = client_for(me).post(
        reverse("chat:conversations"), {"type": "group", "member_ids": [me]}, format="json"
    )
    assert resp.status_code == 400


def test_group_admin_manages_members_and_title(client_for):
    me, a, b = _acct(), _acct(), _acct()
    client = client_for(me)
    group = _group(client, [a])
    roles = {s["account_id"]: s["role"] for s in group["member_states"]}
    assert roles == {me: "admin", a: "member"}

    members = reverse("chat:members", args=[group["id"]])
    assert client.post(members, {"account_ids": [b]}, format="json").status_code == 201
    detail = reverse("chat:conversation", args=[group["id"]])
    assert client.patch(detail, {"title": "new"}, format="json").json()["data"]["title"] == "new"

    member = reverse("chat:member", args=[group["id"], b])
    assert client.delete(member).status_code == 204
    assert client_for(b).get(detail).status_code == 404  # removed: no longer disclosed
    assert client.post(members, {"account_ids": [b]}, format="json").status_code == 201
    assert client_for(b).get(detail).status_code == 200  # same row, restored


def test_ordinary_member_cannot_manage_the_group(client_for):
    me, a, b = _acct(), _acct(), _acct()
    group = _group(client_for(me), [a, b])
    member_client = client_for(a)
    assert (
        member_client.post(
            reverse("chat:members", args=[group["id"]]), {"account_ids": [_acct()]}, format="json"
        ).status_code
        == 403
    )
    assert member_client.delete(reverse("chat:member", args=[group["id"], b])).status_code == 403
    assert (
        member_client.patch(
            reverse("chat:conversation", args=[group["id"]]), {"title": "x"}, format="json"
        ).status_code
        == 403
    )
    message = services.send_message(a, group["id"], body="hi")
    resp = member_client.post(
        reverse("chat:pin", args=[group["id"]]), {"message_id": str(message.id)}, format="json"
    )
    assert resp.status_code == 403


def test_admin_cannot_add_someone_they_blocked(client_for):
    me, a, blocked = _acct(), _acct(), _acct()
    client = client_for(me)
    group = _group(client, [a])
    BlockedPair.objects.create(blocker_id=blocked, blocked_id=me)
    resp = client.post(
        reverse("chat:members", args=[group["id"]]), {"account_ids": [blocked]}, format="json"
    )
    assert resp.status_code == 403


def test_last_admin_leaving_promotes_a_member(client_for):
    me, a, b = _acct(), _acct(), _acct()
    client = client_for(me)
    group = _group(client, [a, b])
    assert client.delete(reverse("chat:member", args=[group["id"], me])).status_code == 204
    data = client_for(a).get(reverse("chat:conversation", args=[group["id"]])).json()["data"]
    assert me not in data["members"]
    assert "admin" in {s["role"] for s in data["member_states"]}


def test_group_cannot_lose_its_only_admin_by_role_change(client_for):
    me, a = _acct(), _acct()
    client = client_for(me)
    group = _group(client, [a])
    resp = client.patch(
        reverse("chat:member", args=[group["id"], me]), {"role": "member"}, format="json"
    )
    assert resp.status_code == 400


def test_dm_has_no_member_management(client_for):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    resp = client_for(me).post(
        reverse("chat:members", args=[conv.id]), {"account_ids": [_acct()]}, format="json"
    )
    assert resp.status_code == 400


def test_voice_message_keeps_duration_and_rejects_absurd_length(client_for):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    url = reverse("chat:voice-messages", args=[conv.id])
    resp = client_for(me).post(
        url, {"media_id": str(uuid.uuid4()), "duration_ms": 4200}, format="json"
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["type"] == "voice"
    assert resp.json()["data"]["attachments"][0]["duration_ms"] == 4200
    resp = client_for(me).post(
        url, {"media_id": str(uuid.uuid4()), "duration_ms": 10**9}, format="json"
    )
    assert resp.status_code == 400
