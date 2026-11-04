"""Who can message me (spec B), marketplace thread lookup, and the page and
support conversations answered by a team (fix track D)."""

import uuid

import pytest
from django.urls import reverse

from chat import services
from chat.models import BlockedPair, Conversation, ConversationMember, Message, OutboxEvent

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _open_dm(client, other: str):
    return client.post(
        reverse("chat:conversations"), {"type": "dm", "other_id": other}, format="json"
    )


# ---- who can message me ------------------------------------------------------


def test_message_setting_defaults_to_everyone_and_can_be_changed(client_for):
    me = _acct()
    client = client_for(me)
    url = reverse("chat:settings")
    assert client.get(url).json()["data"] == {"message_from": "everyone"}
    resp = client.patch(url, {"message_from": "friends"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"message_from": "friends"}
    assert client.get(url).json()["data"]["message_from"] == "friends"
    assert client.patch(url, {"message_from": "nobody"}, format="json").status_code == 400
    # Only the caller's own row is touched.
    assert client_for(_acct()).get(url).json()["data"]["message_from"] == "everyone"


def test_everyone_sends_a_stranger_to_requests(client_for, graph):
    sender, recipient = _acct(), _acct()
    graph.make_strangers(sender, recipient)
    resp = _open_dm(client_for(sender), recipient)
    assert resp.status_code == 201
    member = ConversationMember.objects.get(
        conversation_id=resp.json()["data"]["id"], account_id=recipient
    )
    assert member.request_status == "pending"


def test_friends_only_refuses_strangers_but_not_friends(client_for, graph):
    sender, friend, recipient = _acct(), _acct(), _acct()
    services.set_message_setting(recipient, "friends")
    graph.make_strangers(sender, recipient)
    resp = _open_dm(client_for(sender), recipient)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "messaging_restricted"
    assert not Conversation.objects.filter(type="dm").exists()
    # A friend lands in the inbox as always.
    ok = _open_dm(client_for(friend), recipient)
    assert ok.status_code == 201
    member = ConversationMember.objects.get(
        conversation_id=ok.json()["data"]["id"], account_id=recipient
    )
    assert member.request_status == ""


def test_friends_of_friends_needs_a_mutual_friend(client_for, graph):
    near, far, recipient = _acct(), _acct(), _acct()
    services.set_message_setting(recipient, "friends_of_friends")
    graph.make_strangers(near, recipient)
    graph.make_strangers(far, recipient)
    graph.mutuals.add(frozenset({near, recipient}))
    ok = _open_dm(client_for(near), recipient)
    assert ok.status_code == 201
    member = ConversationMember.objects.get(
        conversation_id=ok.json()["data"]["id"], account_id=recipient
    )
    assert member.request_status == "pending"  # a friend of a friend still waits in requests
    refused = _open_dm(client_for(far), recipient)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "messaging_restricted"


def test_graph_down_with_a_restricted_setting_is_503_not_a_guess(client_for, graph):
    sender, recipient, open_one = _acct(), _acct(), _acct()
    services.set_message_setting(recipient, "friends")
    graph.down = True
    assert _open_dm(client_for(sender), recipient).status_code == 503
    # "everyone" keeps the old safe side: the DM arrives as a request.
    resp = _open_dm(client_for(sender), open_one)
    assert resp.status_code == 201


def test_an_existing_conversation_survives_a_stricter_setting(client_for, graph):
    sender, recipient = _acct(), _acct()
    graph.make_strangers(sender, recipient)
    first = _open_dm(client_for(sender), recipient).json()["data"]["id"]
    services.set_message_setting(recipient, "friends")
    again = _open_dm(client_for(sender), recipient)
    assert again.status_code == 201
    assert again.json()["data"]["id"] == first


def _create_group(client, member_ids):
    return client.post(
        reverse("chat:conversations"),
        {"type": "group", "title": "Team", "member_ids": member_ids},
        format="json",
    )


def _add_members(client, conversation_id, account_ids):
    return client.post(
        reverse("chat:members", args=[conversation_id]),
        {"account_ids": account_ids},
        format="json",
    )


def _folder(client, folder):
    rows = client.get(reverse("chat:conversations"), {"folder": folder}).json()["data"]
    return {r["id"] for r in rows}


def test_a_group_does_not_get_around_friends_only(client_for, graph):
    stranger, recipient = _acct(), _acct()
    services.set_message_setting(recipient, "friends")
    graph.make_strangers(stranger, recipient)
    resp = _create_group(client_for(stranger), [recipient])
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "messaging_restricted"
    assert not Conversation.objects.filter(type="group").exists()
    assert not OutboxEvent.objects.filter(event_type="conversation.member.changed").exists()


def test_a_strangers_group_lands_in_message_requests(client_for, graph):
    stranger, recipient, friend = _acct(), _acct(), _acct()
    graph.make_strangers(stranger, recipient)  # recipient: default "everyone"
    resp = _create_group(client_for(stranger), [recipient, friend])
    assert resp.status_code == 201
    group = resp.json()["data"]["id"]
    states = dict(
        ConversationMember.objects.filter(conversation_id=group).values_list(
            "account_id", "request_status"
        )
    )
    assert states[uuid.UUID(recipient)] == "pending"
    assert states[uuid.UUID(friend)] == ""  # a friend of the creator joins in the inbox
    assert states[uuid.UUID(stranger)] == ""

    services.send_message(stranger, group, body="hi all")
    reader = client_for(recipient)
    assert group in _folder(reader, "requests")
    assert group not in _folder(reader, "inbox")
    assert reader.get(reverse("chat:unread")).json()["data"]["messages"] == 0
    # Accepting moves it to the inbox, like a DM request.
    accepted = reader.post(
        reverse("chat:request", args=[group]), {"action": "accept"}, format="json"
    )
    assert accepted.status_code in (200, 204)
    assert group in _folder(reader, "inbox")


def test_adding_members_follows_each_ones_setting(client_for, graph):
    admin, friend, closed, far, open_one = _acct(), _acct(), _acct(), _acct(), _acct()
    services.set_message_setting(closed, "friends")
    services.set_message_setting(far, "friends_of_friends")
    for other in (closed, far, open_one):
        graph.make_strangers(admin, other)
    client = client_for(admin)
    group = _create_group(client, [friend]).json()["data"]["id"]

    for refused in (closed, far):
        resp = _add_members(client, group, [refused])
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "messaging_restricted"
    # One refusal refuses the whole call: nobody is added.
    assert _add_members(client, group, [open_one, closed]).status_code == 403
    assert set(services.member_ids(Conversation.objects.get(id=group))) == {admin, friend}

    assert _add_members(client, group, [open_one]).status_code == 201
    member = ConversationMember.objects.get(conversation_id=group, account_id=open_one)
    assert member.request_status == "pending"

    graph.down = True  # a restricted setting is never guessed
    assert _add_members(client, group, [closed]).status_code == 503


def test_a_member_who_left_and_is_added_back_by_a_stranger_waits_in_requests(client_for, graph):
    admin, other = _acct(), _acct()
    client = client_for(admin)
    group = _create_group(client, [other]).json()["data"]["id"]
    services.remove_member(other, group, other)
    graph.make_strangers(admin, other)  # they unfriended since
    services.set_message_setting(other, "friends")
    assert _add_members(client, group, [other]).status_code == 403
    services.set_message_setting(other, "everyone")
    assert _add_members(client, group, [other]).status_code == 201
    member = ConversationMember.objects.get(conversation_id=group, account_id=other)
    assert member.left_at is None and member.request_status == "pending"


def test_a_block_keeps_an_account_out_of_a_group(client_for):
    admin, blocked, friend = _acct(), _acct(), _acct()
    BlockedPair.objects.create(blocker_id=blocked, blocked_id=admin)
    client = client_for(admin)
    assert _create_group(client, [blocked, friend]).status_code == 403
    group = _create_group(client, [friend]).json()["data"]["id"]
    assert _add_members(client, group, [blocked]).status_code == 403


def test_a_group_call_does_not_ring_a_member_with_the_group_in_requests(graph):
    from calls import services as calls

    stranger, waiting, friend = _acct(), _acct(), _acct()
    graph.make_strangers(stranger, waiting)
    group = services.create_group(stranger, [waiting, friend])
    assert calls._callees(group, stranger) == [friend]


# ---- marketplace thread lookup ----------------------------------------------


def test_marketplace_threads_filter_by_listing_and_counterpart(client_for):
    seller, buyer1, buyer2 = _acct(), _acct(), _acct()
    listing, other_listing = _acct(), _acct()
    one = services.create_marketplace_conversation(buyer1, seller, listing)
    two = services.create_marketplace_conversation(buyer2, seller, listing)
    services.create_marketplace_conversation(buyer1, seller, other_listing)
    services.create_or_get_dm(buyer1, seller)  # a plain DM is never a listing thread

    client = client_for(seller)
    url = reverse("chat:conversations")
    rows = client.get(url, {"type": "marketplace", "listing_id": listing}).json()["data"]
    assert {r["id"] for r in rows} == {str(one.id), str(two.id)}
    rows = client.get(url, {"type": "marketplace", "listing_id": listing, "with": buyer1}).json()[
        "data"
    ]
    assert [r["id"] for r in rows] == [str(one.id)]
    # The buyer sees only their own thread.
    rows = (
        client_for(buyer2).get(url, {"type": "marketplace", "listing_id": listing}).json()["data"]
    )
    assert [r["id"] for r in rows] == [str(two.id)]
    assert client.get(url, {"listing_id": "nope"}).status_code == 400


# ---- page conversations ------------------------------------------------------


def _write_to_page(client, page_id):
    return client.post(
        reverse("chat:conversations"), {"type": "page", "page_id": page_id}, format="json"
    )


def test_a_member_writes_to_a_page_and_its_team_answers_as_the_page(client_for, profile):
    owner, editor, visitor, analyst = _acct(), _acct(), _acct(), _acct()
    page = profile.add_page(team={owner: "owner", editor: "editor", analyst: "analyst"})
    resp = _write_to_page(client_for(visitor), page)
    assert resp.status_code == 201
    conv = resp.json()["data"]
    assert conv["type"] == "page" and conv["page_id"] == page and conv["title"] == "Cafe Tara"
    assert conv["members"] == [visitor]  # the team is never listed to the visitor
    # Idempotent.
    assert _write_to_page(client_for(visitor), page).json()["data"]["id"] == conv["id"]
    services.send_message(visitor, conv["id"], body="Are you open on Friday?")

    team_url = reverse("chat:team")
    inbox = client_for(editor).get(team_url, {"page_id": page}).json()["data"]
    assert [r["id"] for r in inbox] == [conv["id"]]
    assert inbox[0]["account_id"] == visitor and inbox[0]["team_unread"] == 1
    # Analysts and outsiders have no page inbox.
    assert client_for(analyst).get(team_url, {"page_id": page}).status_code == 404
    assert client_for(visitor).get(team_url, {"page_id": page}).status_code == 404

    reply = client_for(editor).post(
        reverse("chat:team-messages", args=[conv["id"]]), {"body": "Yes, 9 to 5."}, format="json"
    )
    assert reply.status_code == 201
    assert reply.json()["data"]["sender_id"] == page
    assert reply.json()["data"]["author_id"] == editor  # the team sees who answered

    seen = client_for(visitor).get(reverse("chat:messages", args=[conv["id"]])).json()["data"]
    answer = next(m for m in seen if m["body"] == "Yes, 9 to 5.")
    assert answer["sender_id"] == page
    assert "author_id" not in answer  # the visitor never learns which teammate wrote
    event = OutboxEvent.objects.filter(event_type="message.created").latest("created_at")
    payload = event.payload["payload"]
    assert payload["sender"] == page
    assert payload["recipients"] == [visitor]
    assert payload["sender_as"] == {"kind": "page", "id": page, "name": "Cafe Tara"}
    assert editor not in str(event.payload)
    # Answering read the thread for the whole team.
    inbox = client_for(owner).get(team_url, {"page_id": page}).json()["data"]
    assert inbox[0]["team_unread"] == 0


def test_page_conversation_rules(client_for, profile):
    owner, visitor = _acct(), _acct()
    draft = profile.add_page(status="draft", team={owner: "owner"})
    live = profile.add_page(team={owner: "owner"})
    assert _write_to_page(client_for(visitor), draft).status_code == 404
    assert _write_to_page(client_for(visitor), str(uuid.uuid4())).status_code == 404
    assert _write_to_page(client_for(owner), live).status_code == 400  # it's their own page
    profile.down = True
    assert _write_to_page(client_for(visitor), live).status_code == 503


def test_a_removed_teammate_loses_the_page_inbox_at_once(client_for, profile):
    owner, editor, visitor = _acct(), _acct(), _acct()
    page = profile.add_page(team={owner: "owner", editor: "editor"})
    conv = _write_to_page(client_for(visitor), page).json()["data"]["id"]
    services.send_message(visitor, conv, body="hello")
    assert client_for(editor).get(reverse("chat:team-messages", args=[conv])).status_code == 200
    del profile.pages[page]["team"][editor]
    assert client_for(editor).get(reverse("chat:team-messages", args=[conv])).status_code == 404
    reply = client_for(editor).post(
        reverse("chat:team-messages", args=[conv]), {"body": "x"}, format="json"
    )
    assert reply.status_code == 404
    assert not Message.objects.filter(author_id=editor).exists()


def test_a_dm_is_never_reachable_through_the_team_api(client_for, profile):
    a, b = _acct(), _acct()
    dm = services.create_or_get_dm(a, b)
    services.send_message(a, str(dm.id), body="private")
    staff = client_for(_acct(), roles=["moderator"])
    assert staff.get(reverse("chat:team-messages", args=[dm.id])).status_code == 404


# ---- support conversations ---------------------------------------------------


def test_contact_support_and_staff_answer_as_tara_support(client_for):
    member, moderator, admin, someone = _acct(), _acct(), _acct(), _acct()
    resp = client_for(member).post(
        reverse("chat:conversations"), {"type": "support"}, format="json"
    )
    assert resp.status_code == 201
    conv = resp.json()["data"]
    assert conv["type"] == "support" and conv["members"] == [member]
    again = client_for(member).post(
        reverse("chat:conversations"), {"type": "support"}, format="json"
    )
    assert again.json()["data"]["id"] == conv["id"]
    # No message yet: not in the support inbox.
    staff = client_for(moderator, roles=["moderator"])
    assert staff.get(reverse("chat:team")).json()["data"] == []
    services.send_message(member, conv["id"], body="I can't change my name")

    rows = staff.get(reverse("chat:team")).json()["data"]
    assert [r["id"] for r in rows] == [conv["id"]]
    assert client_for(admin, roles=["admin"]).get(reverse("chat:team")).status_code == 200
    assert client_for(someone).get(reverse("chat:team")).status_code == 404
    assert client_for(someone, roles=["ad_reviewer"]).get(reverse("chat:team")).status_code == 404

    reply = staff.post(
        reverse("chat:team-messages", args=[conv["id"]]), {"body": "We're on it."}, format="json"
    )
    assert reply.status_code == 201
    assert reply.json()["data"]["sender_id"] == str(services.SUPPORT_SENDER_ID)
    seen = client_for(member).get(reverse("chat:messages", args=[conv["id"]])).json()["data"]
    assert any(m["sender_id"] == str(services.SUPPORT_SENDER_ID) for m in seen)
    unread = client_for(member).get(reverse("chat:unread")).json()["data"]
    assert unread["messages"] == 1
    assert staff.post(reverse("chat:team-read", args=[conv["id"]])).status_code == 204
    # A member who isn't staff cannot answer someone else's support thread.
    other = client_for(someone).post(
        reverse("chat:team-messages", args=[conv["id"]]), {"body": "hi"}, format="json"
    )
    assert other.status_code == 404


# ---- the team hears of a new message (notification + inbox badge) -------------


def test_a_message_to_a_page_tells_its_team_and_counts_on_the_badge(client_for, profile):
    owner, editor, analyst, visitor = _acct(), _acct(), _acct(), _acct()
    page = profile.add_page(team={owner: "owner", editor: "editor", analyst: "analyst"})
    conv = _write_to_page(client_for(visitor), page).json()["data"]["id"]
    badge = reverse("chat:team-unread")
    assert client_for(owner).get(badge, {"page_id": page}).json()["data"] == {"conversations": 0}

    services.send_message(visitor, conv, body="Do you deliver?")
    payload = (
        OutboxEvent.objects.filter(event_type="message.created").latest("created_at").payload
    )["payload"]
    assert payload["recipients"] == [visitor]  # the team is still not a member
    assert payload["team"] == {
        "kind": "page",
        "page_id": page,
        "name": "Cafe Tara",
        "recipients": sorted([owner, editor]),  # analysts do not answer messages
    }
    assert client_for(editor).get(badge, {"page_id": page}).json()["data"] == {"conversations": 1}
    # Off the team: the badge does not exist either.
    assert client_for(analyst).get(badge, {"page_id": page}).status_code == 404
    assert client_for(visitor).get(badge, {"page_id": page}).status_code == 404

    # Reading (or answering) clears it for the whole team.
    client_for(owner).post(reverse("chat:team-read", args=[conv]))
    assert client_for(editor).get(badge, {"page_id": page}).json()["data"] == {"conversations": 0}
    client_for(editor).post(
        reverse("chat:team-messages", args=[conv]), {"body": "Yes."}, format="json"
    )
    reply = OutboxEvent.objects.filter(event_type="message.created").latest("created_at")
    assert "team" not in reply.payload["payload"]  # the team's own reply tells nobody on it


def test_profile_down_keeps_the_message_and_only_loses_the_teams_notice(client_for, profile):
    owner, visitor = _acct(), _acct()
    page = profile.add_page(team={owner: "owner"})
    conv = _write_to_page(client_for(visitor), page).json()["data"]["id"]
    profile.down = True
    services.send_message(visitor, conv, body="hello?")
    payload = (
        OutboxEvent.objects.filter(event_type="message.created").latest("created_at").payload
    )["payload"]
    assert payload["team"]["recipients"] == []
    assert Message.objects.filter(conversation_id=conv, body="hello?").exists()


def test_the_support_inbox_badge_counts_unanswered_threads_for_staff_only(client_for):
    member, other = _acct(), _acct()
    staff = client_for(_acct(), roles=["moderator"])
    badge = reverse("chat:team-unread")
    for who in (member, other):
        conv = services.open_support_conversation(who)
        services.send_message(who, str(conv.id), body="help")
    assert staff.get(badge).json()["data"] == {"conversations": 2}
    assert client_for(member).get(badge).status_code == 404
    first = services.open_support_conversation(member)
    staff.post(reverse("chat:team-messages", args=[first.id]), {"body": "Sure"}, format="json")
    assert staff.get(badge).json()["data"] == {"conversations": 1}
    payload = (
        OutboxEvent.objects.filter(event_type="message.created").order_by("created_at").first()
    ).payload["payload"]
    assert payload["team"]["kind"] == "support"


# ---- marketplace rows: the listing's title and cover --------------------------


def test_a_marketplace_thread_keeps_the_listings_title_and_cover(client_for):
    from chat.handlers import on_listing_changed, on_marketplace_contact
    from tara_events.envelope import EventEnvelope

    seller, buyer = _acct(), _acct()
    listing, cover, new_cover = _acct(), _acct(), _acct()

    def envelope(event_type, payload):
        return EventEnvelope(
            event_type=event_type, subject_id=listing, payload=payload, producer="marketplace"
        )

    on_marketplace_contact(
        envelope(
            "marketplace.contact.requested",
            {
                "listing_id": listing,
                "seller_id": seller,
                "buyer_id": buyer,
                "title": "Oak desk",
                "cover_media_id": cover,
            },
        )
    )
    url = reverse("chat:conversations")
    row = client_for(seller).get(url, {"type": "marketplace"}).json()["data"][0]
    assert (row["listing_id"], row["listing_title"], row["listing_cover_media_id"]) == (
        listing,
        "Oak desk",
        cover,
    )

    on_listing_changed(
        envelope(
            "listing.updated",
            {"listing_id": listing, "title": "Oak desk, 120cm", "cover_media_id": new_cover},
        )
    )
    row = client_for(buyer).get(url, {"type": "marketplace"}).json()["data"][0]
    assert (row["listing_title"], row["listing_cover_media_id"]) == ("Oak desk, 120cm", new_cover)

    # Moderators removed it: the photo goes, the title stays.
    on_listing_changed(
        envelope(
            "listing.status.changed",
            {
                "listing_id": listing,
                "to": "removed",
                "status": "removed",
                "title": "Oak desk, 120cm",
                "cover_media_id": new_cover,
            },
        )
    )
    row = client_for(buyer).get(url, {"type": "marketplace"}).json()["data"][0]
    assert (row["listing_title"], row["listing_cover_media_id"]) == ("Oak desk, 120cm", None)
    # An older event without the searchable state changes nothing.
    on_listing_changed(envelope("listing.updated", {"listing_id": listing}))
    assert Conversation.objects.get(listing_id=listing).listing_title == "Oak desk, 120cm"
