"""Messenger features: read state and unread counts, delivery, archive and
clear-for-me, edit/delete/forward, search, shared media, private attachments,
and presence peers. Every feature is checked for outsiders and blocked pairs."""

import time
import uuid
from datetime import timedelta

import jwt
import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from chat import services
from chat.media_client import signed as real_signed  # before the fake replaces it
from chat.models import (
    BlockedPair,
    Conversation,
    ConversationMember,
    Message,
    MessageAttachment,
    OutboxEvent,
)
from chat.text import normalize

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _dm(a=None, b=None):
    a, b = a or _acct(), b or _acct()
    return a, b, services.create_or_get_dm(a, b)


def _send(sender, conv, body="hi", **kw):
    return services.send_message(sender, str(conv.id), body=body, **kw)


def _events(event_type):
    return [e.payload["payload"] for e in OutboxEvent.objects.filter(event_type=event_type)]


def _conv(client, conv):
    return client.get(reverse("chat:conversation", args=[conv.id])).json()["data"]


# ---- read state, unread counts, delivery ------------------------------------


def test_messages_get_a_gap_free_sequence(client_for):
    a, b, conv = _dm()
    seqs = [_send(a if i % 2 else b, conv, f"m{i}").seq for i in range(4)]
    assert seqs == [1, 2, 3, 4]
    conv.refresh_from_db()
    assert conv.last_seq == 4


def test_unread_counts_per_conversation_and_total_badge(client_for):
    me = _acct()
    _, peer, conv = _dm(me)
    _, peer2, conv2 = _dm(me)
    for _ in range(3):
        _send(peer, conv)
    _send(peer2, conv2)

    client = client_for(me)
    inbox = {c["id"]: c for c in client.get(reverse("chat:conversations")).json()["data"]}
    assert inbox[str(conv.id)]["unread_count"] == 3
    assert inbox[str(conv2.id)]["unread_count"] == 1
    assert client.get(reverse("chat:unread")).json()["data"] == {
        "messages": 4,
        "conversations": 2,
        "requests": 0,
    }
    # The sender has nothing unread in what they sent.
    assert _conv(client_for(peer), conv)["unread_count"] == 0

    last = Message.objects.filter(conversation=conv).order_by("-seq").first()
    services.mark_read(me, str(conv.id), str(last.id))
    assert client.get(reverse("chat:unread")).json()["data"] == {
        "messages": 1,
        "conversations": 1,
        "requests": 0,
    }


def test_badge_leaves_out_muted_and_archived_conversations(client_for):
    me = _acct()
    _, p1, muted = _dm(me)
    _, p2, archived = _dm(me)
    _, p3, normal = _dm(me)
    services.set_mute(me, str(muted.id), timezone.now() + timedelta(hours=1))
    services.set_archived(me, str(archived.id), True)
    services.set_mute(me, str(archived.id), timezone.now() + timedelta(hours=1))
    for peer, conv in ((p1, muted), (p2, archived), (p3, normal)):
        _send(peer, conv)
    assert client_for(me).get(reverse("chat:unread")).json()["data"]["conversations"] == 1


def test_read_pointer_never_moves_backwards(client_for):
    a, b, conv = _dm()
    first = _send(a, conv, "one")
    second = _send(a, conv, "two")
    client = client_for(b)
    url = reverse("chat:read", args=[conv.id])
    assert client.post(url, {"up_to_message_id": str(second.id)}, format="json").status_code == 200
    before = len(_events("message.read"))
    assert client.post(url, {"up_to_message_id": str(first.id)}, format="json").status_code == 200
    member = ConversationMember.objects.get(conversation=conv, account_id=b)
    assert member.last_read_seq == 2
    assert member.last_read_message_id == second.id
    assert member.last_delivered_seq == 2  # reading implies delivery
    assert len(_events("message.read")) == before  # nothing moved, nothing said


def test_read_requires_membership_and_a_visible_message(client_for):
    a, b, conv = _dm()
    msg = _send(a, conv)
    url = reverse("chat:read", args=[conv.id])
    outsider = client_for(_acct())
    assert outsider.post(url, {"up_to_message_id": str(msg.id)}, format="json").status_code == 404
    services.hide_for_me(b, str(msg.id))
    resp = client_for(b).post(url, {"up_to_message_id": str(msg.id)}, format="json")
    assert resp.status_code == 404


def test_group_read_events_go_only_to_reader_and_affected_senders(client_for):
    admin, s1, s2, quiet = _acct(), _acct(), _acct(), _acct()
    conv = services.create_group(admin, [s1, s2, quiet], "team")
    _send(s1, conv, "from s1")
    last = _send(s2, conv, "from s2")
    services.mark_read(admin, str(conv.id), str(last.id))
    event = _events("message.read")[-1]
    assert set(event["recipients"]) == {admin, s1, s2}
    assert quiet not in event["recipients"]
    assert event["up_to_seq"] == 2


def test_delivered_moves_every_pointer_and_tells_the_sender(client_for):
    me = _acct()
    _, peer, conv = _dm(me)
    _send(peer, conv)
    _send(peer, conv)
    client = client_for(me)
    resp = client.post(reverse("chat:delivered"))
    assert resp.json()["data"] == {"conversations": 1}
    member = ConversationMember.objects.get(conversation=conv, account_id=me)
    assert member.last_delivered_seq == 2
    assert member.last_read_seq == 0  # delivered is not read
    event = _events("message.delivered")[-1]
    assert event["up_to_seq"] == 2 and peer in event["recipients"]
    # Nothing new: nothing moves, nothing is emitted.
    assert client.post(reverse("chat:delivered")).json()["data"] == {"conversations": 0}
    assert len(_events("message.delivered")) == 1
    states = {s["account_id"]: s for s in _conv(client_for(peer), conv)["member_states"]}
    assert states[me]["last_delivered_seq"] == 2


def test_legacy_conversation_is_numbered_by_the_backfill(client_for):
    a, b, conv = _dm()
    m1 = _send(a, conv, "old one")
    _send(a, conv, "old two")
    # Pretend these predate sequences.
    Message.objects.filter(conversation=conv).update(seq=None)
    Conversation.objects.filter(id=conv.id).update(seq_ready=False, last_seq=0)
    ConversationMember.objects.filter(conversation=conv).update(last_read_seq=0)
    ConversationMember.objects.filter(conversation=conv, account_id=b).update(
        last_read_message_id=m1.id
    )
    assert _conv(client_for(b), conv)["unread_count"] == 1  # legacy count still works

    call_command("backfill_message_seq")

    conv.refresh_from_db()
    assert conv.seq_ready and conv.last_seq == 2
    assert list(
        Message.objects.filter(conversation=conv)
        .order_by("created_at")
        .values_list("seq", flat=True)
    ) == [1, 2]
    assert _conv(client_for(b), conv)["unread_count"] == 1
    assert _send(a, conv, "new").seq == 3


# ---- archive and clear for me -------------------------------------------------


def test_archive_moves_a_conversation_to_the_archived_folder(client_for):
    me = _acct()
    _, peer, conv = _dm(me)
    client = client_for(me)
    resp = client.post(reverse("chat:archive", args=[conv.id]), {"archived": True}, format="json")
    assert resp.status_code == 200 and resp.json()["data"]["archived"] is True
    inbox = client.get(reverse("chat:conversations")).json()["data"]
    archived = client.get(reverse("chat:conversations"), {"archived": "1"}).json()["data"]
    assert [c["id"] for c in inbox] == []
    assert [c["id"] for c in archived] == [str(conv.id)]
    # Per member: the peer still has it in the inbox.
    peer_inbox = client_for(peer).get(reverse("chat:conversations")).json()["data"]
    assert [c["id"] for c in peer_inbox] == [str(conv.id)]


def test_new_message_unarchives_unless_muted():
    me = _acct()
    _, peer, conv = _dm(me)
    services.set_archived(me, str(conv.id), True)
    _send(peer, conv)
    assert ConversationMember.objects.get(conversation=conv, account_id=me).archived_at is None

    services.set_archived(me, str(conv.id), True)
    services.set_mute(me, str(conv.id), timezone.now() + timedelta(hours=1))
    _send(peer, conv)
    assert ConversationMember.objects.get(conversation=conv, account_id=me).archived_at


def test_outsider_cannot_archive_or_clear(client_for):
    _, _, conv = _dm()
    outsider = client_for(_acct())
    assert outsider.post(reverse("chat:archive", args=[conv.id])).status_code == 404
    assert outsider.post(reverse("chat:clear", args=[conv.id])).status_code == 404


def test_clear_hides_earlier_messages_for_me_only(client_for):
    me = _acct()
    _, peer, conv = _dm(me)
    old = _send(peer, conv, "before the clear")
    assert client_for(me).post(reverse("chat:clear", args=[conv.id])).status_code == 204
    new = _send(peer, conv, "after the clear")

    mine = client_for(me).get(reverse("chat:messages", args=[conv.id])).json()["data"]
    theirs = client_for(peer).get(reverse("chat:messages", args=[conv.id])).json()["data"]
    assert [m["id"] for m in mine] == [str(new.id)]
    assert {m["id"] for m in theirs} == {str(old.id), str(new.id)}
    assert _conv(client_for(me), conv)["unread_count"] == 1
    # A cleared message is gone for me everywhere: detail, search, receipts.
    assert client_for(me).get(reverse("chat:message", args=[old.id])).status_code == 404
    found = client_for(me).get(reverse("chat:message-search"), {"q": "clear"}).json()["data"]
    assert [m["id"] for m in found] == [str(new.id)]


# ---- edit -------------------------------------------------------------------


def test_sender_edits_within_the_window(client_for):
    a, b, conv = _dm()
    msg = _send(a, conv, "helo")
    resp = client_for(a).patch(
        reverse("chat:message", args=[msg.id]), {"body": "hello"}, format="json"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["body"] == "hello"
    assert resp.json()["data"]["edited_at"] is not None
    msg.refresh_from_db()
    assert msg.body_norm == "hello"
    assert list(msg.edits.values_list("previous_body", flat=True)) == ["helo"]
    assert _events("message.edited")[-1]["message_id"] == str(msg.id)


def test_edit_rules(client_for):
    a, b, conv = _dm()
    msg = _send(a, conv, "hi")
    url = reverse("chat:message", args=[msg.id])
    assert client_for(b).patch(url, {"body": "x"}, format="json").status_code == 403
    assert client_for(_acct()).patch(url, {"body": "x"}, format="json").status_code == 404
    Message.objects.filter(id=msg.id).update(created_at=timezone.now() - timedelta(minutes=16))
    resp = client_for(a).patch(url, {"body": "late"}, format="json")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "edit_window_expired"


def test_blocked_sender_cannot_edit(client_for):
    a, b, conv = _dm()
    msg = _send(a, conv, "hi")
    BlockedPair.objects.create(blocker_id=b, blocked_id=a)
    resp = client_for(a).patch(reverse("chat:message", args=[msg.id]), {"body": "x"}, format="json")
    assert resp.status_code == 403


# ---- delete --------------------------------------------------------------------


def test_delete_for_me_hides_only_for_me(client_for):
    a, b, conv = _dm()
    msg = _send(a, conv, "secret")
    url = reverse("chat:message", args=[msg.id])
    assert client_for(b).delete(url).status_code == 204
    assert client_for(b).get(url).status_code == 404
    assert client_for(a).get(url).status_code == 200
    assert client_for(b).get(reverse("chat:messages", args=[conv.id])).json()["data"] == []
    resp = client_for(b).post(
        reverse("chat:message-reactions", args=[msg.id]), {"type": "like"}, format="json"
    )
    assert resp.status_code == 404
    # Outsiders get the same 404 as for a message that does not exist.
    assert client_for(_acct()).delete(url).status_code == 404


def test_delete_for_everyone_leaves_a_tombstone(client_for, media):
    a, b, conv = _dm()
    att = [{"media_id": media.add(a), "kind": "image"}]
    msg = _send(a, conv, "oops", attachments=att)
    reply = _send(b, conv, "what?", reply_to_id=str(msg.id))
    services.pin_message(a, str(conv.id), str(msg.id))

    url = reverse("chat:message", args=[msg.id]) + "?scope=everyone"
    assert client_for(b).delete(url).status_code == 403  # not the sender
    assert client_for(a).delete(url).status_code == 204

    data = client_for(b).get(reverse("chat:message", args=[msg.id])).json()["data"]
    assert data["deleted"] is True and data["body"] == "" and data["attachments"] == []
    msg.refresh_from_db()
    assert msg.body_norm == "" and not MessageAttachment.objects.filter(message=msg).exists()
    assert _conv(client_for(a), conv)["pinned_messages"] == []
    preview = client_for(a).get(reverse("chat:message", args=[reply.id])).json()["data"]
    assert preview["reply_preview"] == {
        "id": str(msg.id),
        "sender_id": a,
        "type": "image",
        "body": "",
        "deleted": True,
    }
    assert _events("message.deleted")[-1]["scope"] == "everyone"
    # A tombstone cannot be edited or reacted to.
    patch = client_for(a).patch(
        reverse("chat:message", args=[msg.id]), {"body": "x"}, format="json"
    )
    assert patch.status_code == 409


def test_delete_for_everyone_has_a_window(client_for):
    a, b, conv = _dm()
    msg = _send(a, conv)
    Message.objects.filter(id=msg.id).update(created_at=timezone.now() - timedelta(hours=2))
    resp = client_for(a).delete(reverse("chat:message", args=[msg.id]) + "?scope=everyone")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "delete_window_expired"
    bad = client_for(a).delete(reverse("chat:message", args=[msg.id]) + "?scope=all")
    assert bad.status_code == 400


def test_moderation_removal_hides_and_can_be_reversed(client_for):
    a, b, conv = _dm()
    msg = _send(a, conv, "bad")
    services.remove_message(str(msg.id))
    assert client_for(a).get(reverse("chat:message", args=[msg.id])).status_code == 404
    assert _events("message.deleted")[-1]["scope"] == "moderation"
    services.restore_message(str(msg.id))
    assert client_for(a).get(reverse("chat:message", args=[msg.id])).status_code == 200


# ---- forward -------------------------------------------------------------------


def test_forward_copies_attachments_by_reference(client_for, media):
    me = _acct()
    src_peer, _, source = _dm(_acct(), me)
    _, target_peer, target = _dm(me)
    media_id = media.add(src_peer)
    original = _send(
        src_peer, source, "look", attachments=[{"media_id": media_id, "kind": "image"}]
    )

    resp = client_for(me).post(
        reverse("chat:message-forward", args=[original.id]),
        {"conversation_ids": [str(target.id)]},
        format="json",
    )
    assert resp.status_code == 201
    copy = resp.json()["data"][0]
    assert copy["conversation_id"] == str(target.id)
    assert copy["forwarded"] is True and copy["sender_id"] == me
    assert [a["media_id"] for a in copy["attachments"]] == [media_id]
    assert "forwarded_from_message_id" not in copy
    # The target's member can now fetch the attachment through chat.
    url = reverse("chat:message-attachment", args=[copy["id"], media_id])
    assert client_for(target_peer).get(url).status_code == 200
    # A forwarded copy cannot be edited into something the original never said.
    patch = client_for(me).patch(
        reverse("chat:message", args=[copy["id"]]), {"body": "x"}, format="json"
    )
    assert patch.status_code == 403


def test_forward_checks_source_and_every_target(client_for):
    me = _acct()
    _, peer, source = _dm(me)
    msg = _send(peer, source, "hi")
    _, blocked_peer, blocked_conv = _dm(me)
    BlockedPair.objects.create(blocker_id=blocked_peer, blocked_id=me)
    not_mine = services.create_or_get_dm(_acct(), _acct())
    url = reverse("chat:message-forward", args=[msg.id])
    client = client_for(me)

    assert (
        client.post(url, {"conversation_ids": [str(not_mine.id)]}, format="json").status_code == 404
    )
    assert (
        client.post(url, {"conversation_ids": [str(blocked_conv.id)]}, format="json").status_code
        == 403
    )
    outsider = client_for(_acct())
    assert (
        outsider.post(url, {"conversation_ids": [str(source.id)]}, format="json").status_code == 404
    )
    services.hide_for_me(me, str(msg.id))
    assert (
        client.post(url, {"conversation_ids": [str(source.id)]}, format="json").status_code == 404
    )
    # Nothing was written by the refused attempts.
    assert not Message.objects.filter(forwarded_from_message_id=msg.id).exists()


# ---- search ---------------------------------------------------------------------


def test_arabic_normalisation():
    assert normalize("أَحْمَد") == normalize("احمد") == "احمد"
    assert normalize("مدرسة") == normalize("مدرسه")
    assert normalize("مستشفى") == normalize("مستشفي")
    assert normalize("  Hello\tWORLD ") == "hello world"
    assert normalize("٢٠٢٦") == "2026"
    assert normalize("كـــتاب") == "كتاب"


def test_global_search_is_arabic_aware_and_limited_to_my_conversations(client_for):
    me = _acct()
    _, peer, conv = _dm(me)
    hit = _send(peer, conv, "قابلت أحمد اليوم")
    _send(peer, conv, "nothing here")
    stranger, other, theirs = _dm()
    _send(stranger, theirs, "أحمد في محادثة أخرى")

    found = client_for(me).get(reverse("chat:message-search"), {"q": "احمد"}).json()["data"]
    assert [m["id"] for m in found] == [str(hit.id)]
    assert client_for(me).get(reverse("chat:message-search"), {"q": "ا"}).status_code == 400


def test_search_skips_hidden_deleted_and_removed_messages(client_for):
    me = _acct()
    _, peer, conv = _dm(me)
    hidden = _send(peer, conv, "keyword one")
    deleted = _send(peer, conv, "keyword two")
    removed = _send(peer, conv, "keyword three")
    kept = _send(peer, conv, "keyword four")
    services.hide_for_me(me, str(hidden.id))
    services.delete_for_everyone(peer, str(deleted.id))
    services.remove_message(str(removed.id))
    url = reverse("chat:conversation-search", args=[conv.id])
    found = client_for(me).get(url, {"q": "keyword"}).json()["data"]
    assert [m["id"] for m in found] == [str(kept.id)]
    assert client_for(_acct()).get(url, {"q": "keyword"}).status_code == 404


# ---- shared media and attachments ------------------------------------------------


def test_shared_media_panel_filters_and_pages(client_for, media):
    a, b, conv = _dm()
    for _ in range(3):
        _send(a, conv, "", attachments=[{"media_id": media.add(a), "kind": "image"}])
    _send(a, conv, "", attachments=[{"media_id": media.add(a, "file"), "kind": "file"}])
    gone = _send(a, conv, "", attachments=[{"media_id": media.add(a), "kind": "image"}])
    services.delete_for_everyone(a, str(gone.id))
    url = reverse("chat:shared-media", args=[conv.id])
    client = client_for(b)

    page = client.get(url, {"kind": "image", "limit": 2}).json()
    assert len(page["data"]) == 2 and page["page"]["has_more"] is True
    rest = client.get(url, {"kind": "image", "limit": 2, "cursor": page["page"]["next_cursor"]})
    assert len(rest.json()["data"]) == 1
    files = client.get(url, {"kind": "file"}).json()["data"]
    assert [f["kind"] for f in files] == ["file"]
    assert len(client.get(url).json()["data"]) == 4
    assert client.get(url, {"kind": "nope"}).status_code == 400
    assert client_for(_acct()).get(url).status_code == 404


def test_attachments_must_be_my_private_finished_uploads(client_for, media):
    a, b, conv = _dm()
    url = reverse("chat:messages", args=[conv.id])
    client = client_for(a)

    def send(media_id, kind="image", **extra):
        body = {"body": "", "attachments": [{"media_id": media_id, "kind": kind}], **extra}
        return client.post(url, body, format="json")

    assert send(media.add(b)).status_code == 400  # someone else's upload
    assert send(str(uuid.uuid4())).status_code == 400  # unknown to media
    assert send(media.add(a, visibility="public")).status_code == 400
    assert send(media.add(a, status="uploading")).status_code == 400
    assert send(media.add(a, "video"), "image").status_code == 400  # kind mismatch
    assert send(media.add(a, "video", size=65 * 1024 * 1024), "video").status_code == 400
    many = [{"media_id": media.add(a), "kind": "image"} for _ in range(11)]
    assert client.post(url, {"attachments": many}, format="json").status_code == 400
    assert client.post(url, {"body": "x", "type": "system"}, format="json").status_code == 400

    ok = send(media.add(a, "video", size=10 * 1024 * 1024), "video", type="text")
    assert ok.status_code == 201
    assert ok.json()["data"]["type"] == "video"  # derived on the server
    pdf = client.post(
        url,
        {
            "attachments": [
                {"media_id": media.add(a, "file"), "kind": "file", "file_name": "../x/Report.pdf"}
            ]
        },
        format="json",
    )
    assert pdf.json()["data"]["attachments"][0]["file_name"] == "Report.pdf"


def test_media_outage_fails_closed(client_for, media):
    a, b, conv = _dm()
    media_id = media.add(a)
    media.down = True
    resp = client_for(a).post(
        reverse("chat:messages", args=[conv.id]),
        {"attachments": [{"media_id": media_id, "kind": "image"}]},
        format="json",
    )
    assert resp.status_code == 503
    assert not Message.objects.filter(conversation=conv).exists()


def test_attachment_url_only_for_members_who_can_see_the_message(client_for, media):
    a, b, conv = _dm()
    media_id = media.add(a)
    msg = _send(a, conv, "", attachments=[{"media_id": media_id, "kind": "image"}])
    url = reverse("chat:message-attachment", args=[msg.id, media_id])

    data = client_for(b).get(url).json()["data"]
    assert data["url"].startswith("https://storage.test/") and data["thumb_url"]
    assert client_for(_acct()).get(url).status_code == 404
    other = reverse("chat:message-attachment", args=[msg.id, uuid.uuid4()])
    assert client_for(b).get(other).status_code == 404  # not on this message
    services.hide_for_me(b, str(msg.id))
    assert client_for(b).get(url).status_code == 404
    media.down = True
    assert client_for(a).get(url).status_code == 503


# ---- presence peers (internal) -------------------------------------------------------


def _internal(client, audience="chat-internal"):
    from django.conf import settings

    now = int(time.time())
    token = jwt.encode(
        {"iss": "realtime", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_presence_peers_are_dm_peers_without_blocks():
    from rest_framework.test import APIClient

    me = _acct()
    _, friend, _ = _dm(me)
    _, blocked, _ = _dm(me)
    BlockedPair.objects.create(blocker_id=me, blocked_id=blocked)
    group_only = _acct()
    services.create_group(me, [group_only], "g")

    url = reverse("chat_internal:presence-peers", args=[me])
    assert APIClient().get(url).status_code == 401
    assert _internal(APIClient(), "media-internal").get(url).status_code == 401
    peers = _internal(APIClient()).get(url).json()["data"]["peers"]
    assert peers == [friend]


# ---- hardening (review) --------------------------------------------------------


def _envelope(event_type, payload):
    from tara_events.envelope import EventEnvelope

    return EventEnvelope(
        event_type=event_type, subject_id="s", producer="test-service", payload=payload
    )


def test_added_group_member_sees_no_earlier_history_and_nothing_unread(client_for):
    admin, early, late = _acct(), _acct(), _acct()
    group = services.create_group(admin, [early], "g")
    _send(admin, group, "before you joined")
    services.add_members(admin, str(group.id), [late])
    client = client_for(late)

    assert client.get(reverse("chat:messages", args=[group.id])).json()["data"] == []
    assert _conv(client, group)["unread_count"] == 0
    assert client.get(reverse("chat:unread")).json()["data"] == {
        "messages": 0,
        "conversations": 0,
        "requests": 0,
    }
    search = client.get(reverse("chat:message-search"), {"q": "joined"}).json()["data"]
    assert search == []
    after = _send(admin, group, "welcome")
    bodies = [
        m["body"] for m in client.get(reverse("chat:messages", args=[group.id])).json()["data"]
    ]
    assert bodies == ["welcome"]

    # Leaving and coming back does not reveal what was said in between.
    services.remove_member(late, str(group.id), late)
    _send(admin, group, "while you were away")
    services.add_members(admin, str(group.id), [late])
    assert client.get(reverse("chat:messages", args=[group.id])).json()["data"] == []
    assert _conv(client, group)["unread_count"] == 0
    assert client.get(reverse("chat:message", args=[after.id])).status_code == 404


def test_removed_member_loses_live_subscriptions():
    admin, member = _acct(), _acct()
    group = services.create_group(admin, [member], "g")
    services.remove_member(admin, str(group.id), member)
    event = _events("conversation.member.changed")[-1]
    assert (event["action"], event["revoked"]) == ("removed", [member])
    assert member in event["recipients"]


def test_block_revokes_shared_thread_subscriptions_silently():
    from chat import handlers

    a, b, dm = _dm()
    group = services.create_group(a, [b], "g")
    handlers.on_user_blocked(_envelope("user.blocked", {"blocker_id": a, "blocked_id": b}))
    revocations = [e for e in _events("conversation.member.changed") if e["action"] == "blocked"]
    assert [(e["conversation_id"], e["recipients"]) for e in revocations] == [(str(dm.id), [])]
    assert revocations[0]["revoked"] == sorted([a, b])
    # Re-delivery of the same block revokes nothing twice.
    handlers.on_user_blocked(_envelope("user.blocked", {"blocker_id": a, "blocked_id": b}))
    assert len([e for e in _events("conversation.member.changed") if e["action"] == "blocked"]) == 1
    # Realtime's subscribe check now refuses the DM, not the shared group.
    assert services.may_subscribe(b, str(dm.id)) is False
    assert services.may_subscribe(b, str(group.id)) is True


def test_internal_membership_refuses_blocked_pairs_and_is_not_throttled(monkeypatch):
    from rest_framework.test import APIClient

    from tara_common.throttling import ReadThrottle

    a, b, dm = _dm()
    url = reverse("chat_internal:membership", args=[dm.id, b])
    monkeypatch.setattr(ReadThrottle, "rate", "1/min", raising=False)
    client = _internal(APIClient())
    for _ in range(3):  # one service calls for every socket: no per-IP limit
        resp = client.get(url)
        assert resp.status_code == 200 and resp.json()["data"]["is_member"] is True
    BlockedPair.objects.create(blocker_id=a, blocked_id=b)
    assert client.get(url).json()["data"]["is_member"] is False


def test_overturned_moderation_removal_restores_the_message(client_for):
    from chat import handlers

    a, b, conv = _dm()
    msg = _send(a, conv, "appealed")
    payload = {"target_type": "message", "target_id": str(msg.id), "action": "remove"}
    handlers.on_moderation_actioned(_envelope("moderation.actioned", payload))
    handlers.on_moderation_actioned(_envelope("moderation.actioned", payload))
    assert len([e for e in _events("message.deleted") if e["scope"] == "moderation"]) == 1
    assert client_for(b).get(reverse("chat:message", args=[msg.id])).status_code == 404
    handlers.on_moderation_actioned(
        _envelope("moderation.actioned", {**payload, "action": "approve"})
    )
    assert client_for(b).get(reverse("chat:message", args=[msg.id])).status_code == 200


def test_dm_creation_survives_losing_the_race(monkeypatch):
    a, b, first = _dm()
    monkeypatch.setattr(services, "_find_pair", lambda key: None)  # the other request won
    again = services.create_or_get_dm(b, a)
    assert again.id == first.id
    assert ConversationMember.objects.filter(conversation=first).count() == 2


def test_edit_cannot_write_back_a_body_deleted_meanwhile(client_for, monkeypatch):
    a, _, conv = _dm()
    msg = _send(a, conv, "secret")
    real = services.get_visible_message

    def deleted_after_the_check(actor_id, message_id):
        found = real(actor_id, message_id)
        # A delete for everyone lands between the check and the write.
        services._wipe(Message.objects.get(id=msg.id), deleted_by=a)
        return found

    monkeypatch.setattr(services, "get_visible_message", deleted_after_the_check)
    resp = client_for(a).patch(
        reverse("chat:message", args=[msg.id]), {"body": "new"}, format="json"
    )
    assert resp.status_code == 409
    msg.refresh_from_db()
    assert (msg.body, msg.body_norm) == ("", "")
    assert not msg.edits.exists()


def test_group_creation_respects_the_member_cap(client_for):
    me = _acct()
    resp = client_for(me).post(
        reverse("chat:conversations"),
        {"type": "group", "member_ids": [_acct() for _ in range(services.MAX_GROUP_MEMBERS)]},
        format="json",
    )
    assert resp.status_code == 400
    assert not Conversation.objects.filter(type="group").exists()


def test_new_group_member_sees_no_quote_or_pin_from_before_joining(client_for):
    admin, early, late = _acct(), _acct(), _acct()
    group = services.create_group(admin, [early], "g")
    old = _send(admin, group, "old secret")
    services.pin_message(admin, str(group.id), str(old.id))
    services.add_members(admin, str(group.id), [late])
    reply = _send(early, group, "agreed", reply_to_id=str(old.id))
    client = client_for(late)

    [listed] = client.get(reverse("chat:messages", args=[group.id])).json()["data"]
    assert listed["id"] == str(reply.id)
    assert listed["reply_preview"]["body"] == "" and listed["reply_preview"]["deleted"] is True
    detail = client.get(reverse("chat:message", args=[reply.id])).json()["data"]
    assert detail["reply_preview"]["body"] == ""
    assert _conv(client, group)["pinned_messages"] == []
    # Members who were there still see both.
    early_view = client_for(early).get(reverse("chat:message", args=[reply.id])).json()["data"]
    assert early_view["reply_preview"]["body"] == "old secret"
    assert [p["id"] for p in _conv(client_for(early), group)["pinned_messages"]] == [str(old.id)]


def test_member_removed_mid_send_cannot_post(monkeypatch):
    admin, member = _acct(), _acct()
    group = services.create_group(admin, [member], "g")

    def removed_meanwhile(sender_id, items):
        services.remove_member(admin, str(group.id), member)
        return []

    monkeypatch.setattr(services, "_validate_attachments", removed_meanwhile)
    with pytest.raises(services.TaraAPIError) as exc:
        _send(member, group, "sneaky")
    assert exc.value.http_status == 404
    assert not Message.objects.filter(conversation=group).exists()


def test_attachment_url_asks_media_for_the_download_name(client_for, media):
    a, b, conv = _dm()
    named = media.add(a, "file", mime="application/pdf")
    unnamed = media.add(a, "image")
    msg = _send(
        a,
        conv,
        "",
        attachments=[
            {"media_id": named, "kind": "file", "file_name": "uploads/report.pdf"},
            {"media_id": unnamed, "kind": "image"},
        ],
    )
    client = client_for(b)
    assert client.get(reverse("chat:message-attachment", args=[msg.id, named])).status_code == 200
    assert client.get(reverse("chat:message-attachment", args=[msg.id, unnamed])).status_code == 200
    assert media.signed_names == ["report.pdf", None]


def test_media_client_sends_filename_only_when_there_is_one(monkeypatch, settings):
    from chat import media_client

    settings.MEDIA_INTERNAL_URL = "http://media.test"
    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"id": "m", "url": "u"}}

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs["params"]))
        return Response()

    monkeypatch.setattr(media_client.requests, "request", fake_request)
    real_signed(str(uuid.UUID(int=1)), filename="a b.pdf")
    real_signed(str(uuid.UUID(int=1)))
    path = f"http://media.test/internal/v1/media/{uuid.UUID(int=1)}/"
    assert calls == [("GET", path, {"filename": "a b.pdf"}), ("GET", path, None)]


def test_pins_leave_out_messages_the_viewer_hid(client_for):
    a, b, conv = _dm()
    kept, hidden = _send(a, conv, "kept"), _send(a, conv, "hidden")
    for msg in (kept, hidden):
        services.pin_message(a, str(conv.id), str(msg.id))
    services.hide_for_me(b, str(hidden.id))

    assert [p["id"] for p in _conv(client_for(b), conv)["pinned_messages"]] == [str(kept.id)]
    inbox = client_for(b).get(reverse("chat:conversations")).json()["data"]
    assert [p["id"] for p in inbox[0]["pinned_messages"]] == [str(kept.id)]
    # Only for the member who hid it.
    assert len(_conv(client_for(a), conv)["pinned_messages"]) == 2
