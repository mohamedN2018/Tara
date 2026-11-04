"""Message requests, the spam folder, inbox previews and message reports (plan 08 3D)."""

import uuid

import pytest
from django.urls import reverse

from chat import handlers, services
from chat.models import ConversationMember, MessageReport, OutboxEvent
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _folder(client, folder: str, **extra) -> list[str]:
    body = client.get(reverse("chat:conversations"), {"folder": folder, **extra}).json()
    return [c["id"] for c in body["data"]]


def _stranger_dm(graph, sender: str, recipient: str):
    graph.make_strangers(sender, recipient)
    conversation = services.create_or_get_dm(sender, recipient)
    services.send_message(sender, str(conversation.id), body="hello there")
    return conversation


def test_first_message_from_a_non_friend_goes_to_requests(client_for, graph):
    sender, recipient = _acct(), _acct()
    conv = _stranger_dm(graph, sender, recipient)
    client = client_for(recipient)

    assert _folder(client, "requests") == [str(conv.id)]
    assert _folder(client, "inbox") == []
    # The sender's side is an ordinary thread.
    assert _folder(client_for(sender), "inbox") == [str(conv.id)]
    row = client.get(reverse("chat:conversation", args=[conv.id])).json()["data"]
    assert row["request_status"] == "pending"
    sender_row = client_for(sender).get(reverse("chat:conversation", args=[conv.id])).json()
    assert sender_row["data"]["request_status"] == "none"
    # Not in the badge, counted apart.
    unread = client.get(reverse("chat:unread")).json()["data"]
    assert unread == {"messages": 0, "conversations": 0, "requests": 1}


def test_friends_dm_goes_straight_to_the_inbox(client_for):
    sender, recipient = _acct(), _acct()
    conv = services.create_or_get_dm(sender, recipient)
    services.send_message(sender, str(conv.id), body="hi")
    assert _folder(client_for(recipient), "inbox") == [str(conv.id)]
    assert _folder(client_for(recipient), "requests") == []


def test_graph_down_is_treated_as_a_request(client_for, graph):
    sender, recipient = _acct(), _acct()
    graph.down = True
    conv = services.create_or_get_dm(sender, recipient)
    services.send_message(sender, str(conv.id), body="hi")
    assert _folder(client_for(recipient), "requests") == [str(conv.id)]


def test_empty_request_is_not_listed(client_for, graph):
    sender, recipient = _acct(), _acct()
    graph.make_strangers(sender, recipient)
    services.create_or_get_dm(sender, recipient)
    assert _folder(client_for(recipient), "requests") == []
    assert client_for(recipient).get(reverse("chat:unread")).json()["data"]["requests"] == 0


def test_a_request_message_is_muted_for_the_recipient(graph):
    sender, recipient = _acct(), _acct()
    _stranger_dm(graph, sender, recipient)
    created = OutboxEvent.objects.filter(event_type="message.created").latest("created_at")
    # `muted` means: delivered, but no notification and no push.
    assert created.payload["payload"]["muted"] == [recipient]


def test_reading_a_request_sends_no_receipt(client_for, graph):
    sender, recipient = _acct(), _acct()
    conv = _stranger_dm(graph, sender, recipient)
    message = conv.messages.get()
    response = client_for(recipient).post(
        reverse("chat:read", args=[conv.id]), {"up_to_message_id": str(message.id)}, format="json"
    )
    assert response.status_code in (200, 204)
    assert not OutboxEvent.objects.filter(event_type="message.read").exists()
    state = ConversationMember.objects.get(conversation=conv, account_id=recipient)
    assert state.last_read_seq == 0


def test_accept_moves_it_to_the_inbox(client_for, graph):
    sender, recipient = _acct(), _acct()
    conv = _stranger_dm(graph, sender, recipient)
    client = client_for(recipient)
    response = client.post(
        reverse("chat:request", args=[conv.id]), {"action": "accept"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["data"]["request_status"] == "none"
    assert _folder(client, "inbox") == [str(conv.id)]
    assert _folder(client, "requests") == []
    changed = OutboxEvent.objects.filter(event_type="conversation.member.changed").latest(
        "created_at"
    )
    assert changed.payload["payload"]["action"] == "request_accepted"
    assert changed.payload["payload"]["recipients"] == [recipient]  # the sender is not told


def test_replying_accepts_the_request(client_for, graph):
    sender, recipient = _acct(), _acct()
    conv = _stranger_dm(graph, sender, recipient)
    services.send_message(recipient, str(conv.id), body="hi back")
    assert _folder(client_for(recipient), "inbox") == [str(conv.id)]


def test_decline_moves_it_to_spam_and_stops_further_messages(client_for, graph):
    sender, recipient = _acct(), _acct()
    conv = _stranger_dm(graph, sender, recipient)
    client = client_for(recipient)
    response = client.post(
        reverse("chat:request", args=[conv.id]), {"action": "decline"}, format="json"
    )
    assert response.json()["data"]["request_status"] == "spam"
    assert _folder(client, "spam") == [str(conv.id)]
    assert _folder(client, "requests") == []

    blocked = client_for(sender).post(
        reverse("chat:messages", args=[conv.id]), {"body": "again?"}, format="json"
    )
    assert blocked.status_code == 403
    # Accepting from the spam folder undoes it.
    client.post(reverse("chat:request", args=[conv.id]), {"action": "accept"}, format="json")
    again = client_for(sender).post(
        reverse("chat:messages", args=[conv.id]), {"body": "again?"}, format="json"
    )
    assert again.status_code == 201


def test_decline_of_an_ordinary_thread_is_a_conflict(client_for):
    a, b = _acct(), _acct()
    conv = services.create_or_get_dm(a, b)
    response = client_for(b).post(
        reverse("chat:request", args=[conv.id]), {"action": "decline"}, format="json"
    )
    assert response.status_code == 409


def test_request_answer_needs_membership(client_for, graph):
    sender, recipient = _acct(), _acct()
    conv = _stranger_dm(graph, sender, recipient)
    response = client_for(_acct()).post(
        reverse("chat:request", args=[conv.id]), {"action": "accept"}, format="json"
    )
    assert response.status_code == 404


def test_becoming_friends_accepts_pending_requests(client_for, graph):
    sender, recipient = _acct(), _acct()
    conv = _stranger_dm(graph, sender, recipient)
    event = EventEnvelope(
        event_type="friendship.accepted",
        payload={"a": recipient, "b": sender},
        subject_id=str(uuid.uuid4()),
        producer="graph-service",
    )
    handlers.on_friendship_accepted(event)
    handlers.on_friendship_accepted(event)  # a replay changes nothing
    assert _folder(client_for(recipient), "inbox") == [str(conv.id)]


def test_requests_share_no_presence(graph):
    sender, recipient = _acct(), _acct()
    _stranger_dm(graph, sender, recipient)
    assert services.presence_peers(recipient) == []
    assert services.presence_peers(sender) == []


def test_requests_flag_off_keeps_every_dm_in_the_inbox(client_for, graph, settings):
    settings.CHAT_MESSAGE_REQUESTS = False
    sender, recipient = _acct(), _acct()
    conv = _stranger_dm(graph, sender, recipient)
    assert _folder(client_for(recipient), "inbox") == [str(conv.id)]
    assert graph.calls == 0


def test_unknown_folder_is_a_400(client_for):
    response = client_for(_acct()).get(reverse("chat:conversations"), {"folder": "nope"})
    assert response.status_code == 400


def test_type_filter_lists_marketplace_threads_only(client_for):
    buyer, seller = _acct(), _acct()
    listing = str(uuid.uuid4())
    market = services.create_marketplace_conversation(buyer, seller, listing)
    services.create_or_get_dm(buyer, seller)
    ids = _folder(client_for(buyer), "inbox", type="marketplace")
    assert ids == [str(market.id)]
    row = client_for(buyer).get(reverse("chat:conversations"), {"type": "marketplace"}).json()
    assert row["data"][0]["listing_id"] == listing


def test_unread_filter_is_server_side(client_for):
    me = _acct()
    read_conv = services.create_or_get_dm(me, _acct())
    unread_conv = services.create_or_get_dm(me, _acct())
    services.send_message(me, str(read_conv.id), body="mine")
    other = [m for m in services.member_ids(unread_conv) if m != me][0]
    services.send_message(other, str(unread_conv.id), body="theirs")
    assert _folder(client_for(me), "inbox", unread=1) == [str(unread_conv.id)]


# ---- the inbox row preview ----------------------------------------------------


def test_last_message_preview_follows_what_the_viewer_can_see(client_for):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    services.send_message(me, str(conv.id), body="first")
    latest = services.send_message(other, str(conv.id), body="second")

    row = client_for(me).get(reverse("chat:conversations")).json()["data"][0]
    assert row["last_message"]["id"] == str(latest.id)
    assert row["last_message"]["body"] == "second"
    assert row["last_message"]["sender_id"] == other

    services.hide_for_me(me, str(latest.id))
    row = client_for(me).get(reverse("chat:conversations")).json()["data"][0]
    assert row["last_message"]["body"] == "first"
    # The other member still sees their own message.
    theirs = client_for(other).get(reverse("chat:conversations")).json()["data"][0]
    assert theirs["last_message"]["body"] == "second"

    services.clear_for_me(me, str(conv.id))
    row = client_for(me).get(reverse("chat:conversations")).json()["data"][0]
    assert row["last_message"] is None


def test_preview_of_a_message_deleted_for_everyone_has_no_body(client_for):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    message = services.send_message(me, str(conv.id), body="oops")
    services.delete_for_everyone(me, str(message.id))
    row = client_for(other).get(reverse("chat:conversations")).json()["data"][0]
    assert row["last_message"]["deleted"] is True
    assert row["last_message"]["body"] == ""


def test_group_preview_starts_at_join(client_for):
    admin, a, late = _acct(), _acct(), _acct()
    conv = services.create_group(admin, [a], "team")
    services.send_message(admin, str(conv.id), body="before you")
    services.add_members(admin, str(conv.id), [late])
    row = client_for(late).get(reverse("chat:conversations")).json()["data"][0]
    assert row["last_message"] is None


# ---- reporting a message ------------------------------------------------------


def test_report_message_emits_once_with_a_text_snapshot(client_for, media):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    image = media.add(other, "image")
    message = services.send_message(
        other,
        str(conv.id),
        body="buy now",
        attachments=[{"media_id": image, "kind": "image"}],
    )
    client = client_for(me)
    url = reverse("chat:message-report", args=[message.id])
    first = client.post(url, {"reason": "spam"}, format="json")
    second = client.post(url, {"reason": "scam"}, format="json")
    assert (first.status_code, second.status_code) == (201, 200)
    assert MessageReport.objects.filter(message=message).count() == 1

    events = OutboxEvent.objects.filter(event_type="message.reported")
    assert events.count() == 1
    payload = events.get().payload["payload"]
    assert payload["reporter"] == me
    assert payload["owner_id"] == other
    assert payload["reason"] == "spam"
    assert payload["snapshot"]["body"] == "buy now"
    assert payload["snapshot"]["attachment_count"] == 1
    # Private attachments never leave the conversation.
    assert image not in str(payload)


def test_report_rules(client_for):
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    mine = services.send_message(me, str(conv.id), body="mine")
    theirs = services.send_message(other, str(conv.id), body="theirs")
    url = reverse("chat:message-report", args=[mine.id])
    assert client_for(me).post(url, {"reason": "spam"}, format="json").status_code == 400
    stranger = client_for(_acct()).post(
        reverse("chat:message-report", args=[theirs.id]), {"reason": "spam"}, format="json"
    )
    assert stranger.status_code == 404
    bad_reason = client_for(me).post(
        reverse("chat:message-report", args=[theirs.id]), {"reason": "meh"}, format="json"
    )
    assert bad_reason.status_code == 400


def test_report_emission_flag(client_for, settings):
    settings.CHAT_EMIT_MESSAGE_REPORTED = False
    me, other = _acct(), _acct()
    conv = services.create_or_get_dm(me, other)
    theirs = services.send_message(other, str(conv.id), body="x")
    client_for(me).post(
        reverse("chat:message-report", args=[theirs.id]), {"reason": "spam"}, format="json"
    )
    assert MessageReport.objects.count() == 1
    assert not OutboxEvent.objects.filter(event_type="message.reported").exists()
