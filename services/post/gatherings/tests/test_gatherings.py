"""Milestone 1.13: events with RSVP, invites, visibility, reports, moderation, reminders."""

from datetime import timedelta

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from posts.handlers import on_moderation_actioned
from posts.models import BlockedPair, OutboxEvent
from rest_framework.test import APIClient

from gatherings import services
from gatherings.handlers import on_user_blocked_drop_rsvps
from gatherings.models import (
    Gathering,
    GatheringInvite,
    GatheringReminderLog,
    GatheringReport,
    GatheringRSVP,
)
from gatherings.tests.conftest import acct, make_event
from tara_common.exceptions import TaraAPIError
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _outbox(event_type: str):
    return [e.payload["payload"] for e in OutboxEvent.objects.filter(event_type=event_type)]


def _code(resp) -> str:
    return resp.json()["error"]["code"]


def _future(**kw):
    return (timezone.now() + timedelta(**kw)).isoformat()


def _create(client, **data):
    body = {
        "title": "Book club",
        "starts_at": _future(days=2),
        "location": "Cairo library",
        **data,
    }
    return client.post(reverse("gatherings:event-list"), body, format="json")


def _detail(client, gathering_id):
    return client.get(reverse("gatherings:event-detail", args=[gathering_id]))


def _rsvp(client, gathering_id, status):
    return client.post(
        reverse("gatherings:event-rsvp", args=[gathering_id]), {"status": status}, format="json"
    )


def _list(client, scope, **params):
    return client.get(reverse("gatherings:event-list"), {"scope": scope, **params})


def _ids(resp) -> list[str]:
    assert resp.status_code == 200, resp.content
    return [g["id"] for g in resp.json()["data"]]


def _report(client, gathering_id, reason="spam"):
    return client.post(
        reverse("gatherings:event-report", args=[gathering_id]), {"reason": reason}, format="json"
    )


def _actioned(target_id, action):
    on_moderation_actioned(
        EventEnvelope(
            event_type="moderation.actioned",
            subject_id=acct(),
            producer="moderation-service",
            payload={
                "case_id": acct(),
                "target_type": "gathering",
                "target_id": str(target_id),
                "action": action,
            },
        )
    )


# ---- create and validation -------------------------------------------------------


def test_create_returns_the_event_and_emits_ids_and_enums_only(client_for):
    host = acct()
    resp = _create(client_for(host), description="secret plans", capacity=10)
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["is_host"] is True
    assert data["status"] == "scheduled"
    assert data["my_rsvp"] is None
    assert data["spots_left"] == 10
    [payload] = _outbox("gathering.created")
    assert payload["gathering_id"] == data["id"]
    assert payload["host_id"] == host
    assert payload["audience"] == "public"
    text = str(payload)
    assert "Book club" not in text and "secret plans" not in text and "Cairo library" not in text


def test_cover_is_bound_to_the_event_and_restricted(client_for, media_stub):
    host = acct()
    cover = media_stub.add(host)
    resp = _create(client_for(host), cover_media_id=cover)
    assert resp.status_code == 201, resp.content
    [bind] = media_stub.binds
    assert bind == {
        "owner_id": host,
        "post_id": resp.json()["data"]["id"],
        "ids": [cover],
        "restricted": True,
    }


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [("video", "ready", "media_kind_not_allowed"), ("image", "uploading", "media_not_ready")],
)
def test_a_cover_must_be_a_ready_image(client_for, media_stub, kind, status, code):
    host = acct()
    cover = media_stub.add(host, kind=kind, status=status)
    resp = _create(client_for(host), cover_media_id=cover)
    assert resp.status_code == 400
    assert _code(resp) == code
    assert not Gathering.objects.exists()
    assert not media_stub.binds


def test_someone_elses_media_cannot_be_a_cover(client_for, media_stub):
    cover = media_stub.add(acct())
    resp = _create(client_for(acct()), cover_media_id=cover)
    assert _code(resp) == "media_not_owned"
    assert not _outbox("gathering.created")


def test_media_down_fails_closed_with_503(client_for, media_stub):
    host = acct()
    cover = media_stub.add(host)
    media_stub.down = True
    resp = _create(client_for(host), cover_media_id=cover)
    assert resp.status_code == 503
    assert not Gathering.objects.exists()


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "ftp://example.com/x", "data:text/html,hi", "https://", "http://a b"],
)
def test_online_links_must_be_http_or_https(client_for, url):
    resp = _create(client_for(acct()), location_type="online", location="", online_url=url)
    assert resp.status_code == 400
    assert _code(resp) == "invalid_url"


def test_an_online_event_with_an_https_link(client_for):
    resp = _create(
        client_for(acct()), location_type="online", location="", online_url="https://meet.example/x"
    )
    assert resp.status_code == 201, resp.content
    assert resp.json()["data"]["online_url"] == "https://meet.example/x"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        ({"starts_at": _future(hours=-1)}, "starts_in_past"),
        ({"starts_at": _future(days=3), "ends_at": _future(days=2)}, "ends_before_start"),
        ({"location": ""}, "location_required"),
        ({"location_type": "online", "location": ""}, "online_url_required"),
        ({"timezone": "Mars/Olympus"}, "invalid_timezone"),
        ({"description": "x" * 5001}, "validation_error"),
        ({"title": "x" * 121}, "validation_error"),
        ({"audience": "everyone"}, "validation_error"),
        ({"capacity": 0}, "validation_error"),
    ],
)
def test_invalid_events_are_refused(client_for, data, code):
    resp = _create(client_for(acct()), **data)
    assert resp.status_code == 400, resp.content
    assert _code(resp) == code
    if code != "validation_error":  # DRF marks the test's transaction for rollback
        assert not Gathering.objects.exists()


# ---- visibility matrix -----------------------------------------------------------

VIEWERS = ["host", "friend", "stranger", "invitee", "rsvper", "blocked_by_host", "blocks_host"]
EXPECTED = {
    "public": {"host", "friend", "stranger", "invitee", "rsvper"},
    "friends": {"host", "friend", "invitee"},
    "invite_only": {"host", "invitee", "rsvper"},
}


@pytest.fixture
def matrix(graph):
    """One event per audience and one account per kind of viewer."""
    people = {name: acct() for name in VIEWERS}
    host = people["host"]
    graph.befriend(host, people["friend"])
    graph.befriend(host, people["invitee"])
    events = {}
    for audience in EXPECTED:
        g = make_event(host, audience=audience, title=f"{audience} event")
        GatheringInvite.objects.create(gathering=g, invitee_id=people["invitee"], inviter_id=host)
        # An RSVP row from before the audience narrowed (or a past invite).
        GatheringRSVP.objects.create(gathering=g, account_id=people["rsvper"], status="interested")
        events[audience] = g
    BlockedPair.objects.create(blocker_id=host, blocked_id=people["blocked_by_host"])
    BlockedPair.objects.create(blocker_id=people["blocks_host"], blocked_id=host)
    return people, events


@pytest.mark.parametrize("audience", list(EXPECTED))
@pytest.mark.parametrize("viewer", VIEWERS)
def test_visibility_matrix_detail_list_attendees_report(client_for, matrix, audience, viewer):
    people, events = matrix
    g = events[audience]
    client = client_for(people[viewer])
    visible = viewer in EXPECTED[audience]

    assert _detail(client, g.id).status_code == (200 if visible else 404)
    assert services.visible_to_viewer(people[viewer], g) is visible
    listed = str(g.id) in _ids(_list(client, "upcoming"))
    assert listed is visible
    attendees = client.get(reverse("gatherings:event-attendees", args=[g.id]))
    assert attendees.status_code == (200 if visible else 404)
    found = client.get(reverse("gatherings:event-list"), {"q": f"{audience} event"})
    assert (str(g.id) in _ids(found)) is visible
    if viewer != "host":
        assert _report(client, g.id).status_code == (202 if visible else 404)
        assert GatheringReport.objects.filter(reporter_id=people[viewer]).exists() is visible


@pytest.mark.parametrize("audience", list(EXPECTED))
def test_internal_visibility_answers_for_the_cover(matrix, audience):
    """Media asks post's visibility endpoint for restricted media; an event id answers."""
    people, events = matrix
    g = events[audience]
    now = int(timezone.now().timestamp())
    token = jwt.encode(
        {"iss": "media", "aud": "post-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    for viewer in VIEWERS:
        resp = client.get(
            reverse("internal-post-visibility", args=[g.id]), {"viewer_id": people[viewer]}
        )
        assert resp.json()["data"]["visible"] is (viewer in EXPECTED[audience]), viewer


def test_friends_only_fails_closed_when_graph_is_down(client_for, graph):
    host, friend = acct(), acct()
    graph.befriend(host, friend)
    g = make_event(host, audience="friends")
    graph.down = True
    client = client_for(friend)
    assert _detail(client, g.id).status_code == 404
    assert str(g.id) not in _ids(_list(client, "upcoming"))


def test_an_ex_friend_loses_a_friends_only_event(client_for, graph):
    host, friend = acct(), acct()
    graph.befriend(host, friend)
    g = make_event(host, audience="friends")
    assert _detail(client_for(friend), g.id).status_code == 200
    graph.unfriend(host, friend)
    assert _detail(client_for(friend), g.id).status_code == 404


def test_attendee_lists_hide_accounts_blocked_either_way(client_for):
    host, viewer, blocked_by_viewer, blocks_viewer, other = (acct() for _ in range(5))
    g = make_event(host)
    for account in (blocked_by_viewer, blocks_viewer, other):
        services.rsvp(account, g.id, "going")
    BlockedPair.objects.create(blocker_id=viewer, blocked_id=blocked_by_viewer)
    BlockedPair.objects.create(blocker_id=blocks_viewer, blocked_id=viewer)

    resp = client_for(viewer).get(
        reverse("gatherings:event-attendees", args=[g.id]), {"status": "going"}
    )
    assert [a["account_id"] for a in resp.json()["data"]] == [other]
    everyone = client_for(host).get(
        reverse("gatherings:event-attendees", args=[g.id]), {"status": "going"}
    )
    assert len(everyone.json()["data"]) == 3


def test_not_going_and_invited_lists_are_for_the_host_only(client_for, graph):
    host, guest, friend = acct(), acct(), acct()
    graph.befriend(host, friend)
    g = make_event(host)
    services.rsvp(guest, g.id, "not_going")
    services.invite(host, g.id, [friend])
    url = reverse("gatherings:event-attendees", args=[g.id])
    for state in ("not_going", "invited"):
        assert client_for(guest).get(url, {"status": state}).status_code == 403
    assert [
        a["account_id"] for a in client_for(host).get(url, {"status": "not_going"}).json()["data"]
    ] == [guest]
    assert [
        a["account_id"] for a in client_for(host).get(url, {"status": "invited"}).json()["data"]
    ] == [friend]


def test_removed_and_deleted_events_are_hidden_from_everyone(client_for):
    host = acct()
    removed, deleted = make_event(host), make_event(host)
    _actioned(removed.id, "remove")
    services.delete_gathering(host, deleted.id)
    for viewer in (host, acct()):
        client = client_for(viewer)
        assert _detail(client, removed.id).status_code == 404
        assert _detail(client, deleted.id).status_code == 404
        listed = _ids(_list(client, "upcoming")) + _ids(_list(client, "hosting"))
        assert str(removed.id) not in listed and str(deleted.id) not in listed


# ---- lists -----------------------------------------------------------------------


def test_scopes(client_for, graph):
    me, friend, stranger = acct(), acct(), acct()
    graph.befriend(me, friend)
    soon = make_event(friend, starts_at=timezone.now() + timedelta(hours=5))
    later = make_event(stranger, starts_at=timezone.now() + timedelta(days=5))
    mine = make_event(me)
    invited = make_event(friend, audience="invite_only")
    services.invite(friend, invited.id, [me])
    services.rsvp(me, later.id, "interested")
    services.rsvp(me, soon.id, "not_going")
    past = make_event(stranger)
    services.rsvp(me, past.id, "going")
    Gathering.objects.filter(id=past.id).update(
        starts_at=timezone.now() - timedelta(days=2), ends_at=timezone.now() - timedelta(days=1)
    )
    hosted_past = make_event(me)
    Gathering.objects.filter(id=hosted_past.id).update(starts_at=timezone.now() - timedelta(days=3))

    client = client_for(me)
    upcoming = _ids(_list(client, "upcoming"))
    assert upcoming == [str(soon.id), str(mine.id), str(invited.id), str(later.id)]
    assert _ids(_list(client, "hosting")) == [str(mine.id)]
    assert _ids(_list(client, "going")) == [str(later.id)]
    assert _ids(_list(client, "invited")) == [str(invited.id)]
    assert _ids(_list(client, "past")) == [str(past.id), str(hosted_past.id)]
    assert _list(client, "nope").status_code == 400


def test_lists_filter_before_paging_so_pages_are_full(client_for, graph):
    me = acct()
    hidden_host = acct()
    for i in range(6):  # friends-only events of a stranger come first in time
        make_event(
            hidden_host, audience="friends", starts_at=timezone.now() + timedelta(hours=i + 1)
        )
    shown = [
        make_event(acct(), starts_at=timezone.now() + timedelta(days=1, hours=i)) for i in range(5)
    ]
    client = client_for(me)
    first = client.get(reverse("gatherings:event-list"), {"scope": "upcoming", "limit": 2})
    body = first.json()
    assert [g["id"] for g in body["data"]] == [str(shown[0].id), str(shown[1].id)]
    assert body["page"]["has_more"] is True
    seen = [g["id"] for g in body["data"]]
    cursor = body["page"]["next_cursor"]
    while cursor:
        page = client.get(
            reverse("gatherings:event-list"), {"scope": "upcoming", "limit": 2, "cursor": cursor}
        ).json()
        assert page["data"], "an empty page with has_more"
        seen += [g["id"] for g in page["data"]]
        cursor = page["page"]["next_cursor"]
    assert seen == [str(g.id) for g in shown]


def test_cancelled_events_leave_upcoming_but_stay_in_going(client_for):
    me, host = acct(), acct()
    g = make_event(host)
    services.rsvp(me, g.id, "going")
    services.cancel_gathering(host, g.id)
    client = client_for(me)
    assert str(g.id) not in _ids(_list(client, "upcoming"))
    going = _list(client, "going").json()["data"]
    assert [(e["id"], e["status"], e["my_rsvp"]) for e in going] == [
        (str(g.id), "cancelled", "going")
    ]


# ---- RSVP ------------------------------------------------------------------------


def test_rsvp_counts_and_events(client_for):
    host, guest = acct(), acct()
    g = make_event(host, capacity=5)
    client = client_for(guest)
    data = _rsvp(client, g.id, "going").json()["data"]
    assert (data["going_count"], data["interested_count"], data["my_rsvp"]) == (1, 0, "going")
    assert data["spots_left"] == 4
    data = _rsvp(client, g.id, "interested").json()["data"]
    assert (data["going_count"], data["interested_count"]) == (0, 1)
    assert _rsvp(client, g.id, "interested").status_code == 200  # same answer: no event
    data = client.delete(reverse("gatherings:event-rsvp", args=[g.id])).json()["data"]
    assert (data["going_count"], data["interested_count"], data["my_rsvp"]) == (0, 0, None)
    events = _outbox("gathering.rsvp")
    assert [(e["status"], e["previous_status"]) for e in events] == [
        ("going", None),
        ("interested", "going"),
        (None, "interested"),
    ]
    assert all(e["host_id"] == host and e["account_id"] == guest for e in events)


def test_the_host_cannot_rsvp(client_for):
    host = acct()
    g = make_event(host)
    resp = _rsvp(client_for(host), g.id, "going")
    assert resp.status_code == 400
    assert _code(resp) == "host_cannot_rsvp"
    assert Gathering.objects.get(id=g.id).going_count == 0


def test_a_full_event_refuses_going_but_not_interested(client_for):
    g = make_event(acct(), capacity=1)
    assert _rsvp(client_for(acct()), g.id, "going").status_code == 200
    late = client_for(acct())
    resp = _rsvp(late, g.id, "going")
    assert resp.status_code == 409
    assert _code(resp) == "event_full"
    assert _rsvp(late, g.id, "interested").status_code == 200
    g.refresh_from_db()
    assert (g.going_count, g.interested_count) == (1, 1)


def test_a_freed_seat_can_be_taken(client_for):
    g = make_event(acct(), capacity=1)
    first, second = client_for(acct()), client_for(acct())
    _rsvp(first, g.id, "going")
    assert _rsvp(second, g.id, "going").status_code == 409
    _rsvp(first, g.id, "not_going")
    assert _rsvp(second, g.id, "going").status_code == 200


@pytest.mark.parametrize("state", ["cancelled", "ended"])
def test_no_rsvp_on_a_cancelled_or_ended_event(client_for, state):
    host = acct()
    g = make_event(host)
    if state == "cancelled":
        services.cancel_gathering(host, g.id)
    else:
        Gathering.objects.filter(id=g.id).update(
            starts_at=timezone.now() - timedelta(hours=5),
            ends_at=timezone.now() - timedelta(hours=1),
        )
    resp = _rsvp(client_for(acct()), g.id, "going")
    assert resp.status_code == 409
    assert _code(resp) == f"event_{state}"
    assert _detail(client_for(host), g.id).json()["data"]["status"] == state


# ---- invites ---------------------------------------------------------------------


def _invite(client, gathering_id, ids):
    return client.post(
        reverse("gatherings:event-invite", args=[gathering_id]), {"account_ids": ids}, format="json"
    )


def test_the_host_invites_friends_and_they_can_see_an_invite_only_event(client_for, graph):
    host, friend = acct(), acct()
    graph.befriend(host, friend)
    g = make_event(host, audience="invite_only")
    assert _detail(client_for(friend), g.id).status_code == 404
    resp = _invite(client_for(host), g.id, [friend, friend])
    assert resp.json()["data"]["invited"] == [friend]
    assert _invite(client_for(host), g.id, [friend]).json()["data"]["invited"] == []
    assert _outbox("gathering.invited") == [
        {"gathering_id": str(g.id), "host_id": host, "invitee_ids": [friend]}
    ]
    data = _detail(client_for(friend), g.id).json()["data"]
    assert data["invited"] is True
    assert str(g.id) in _ids(_list(client_for(friend), "invited"))


def test_only_friends_can_be_invited(client_for, graph):
    host, friend, stranger = acct(), acct(), acct()
    graph.befriend(host, friend)
    g = make_event(host)
    resp = _invite(client_for(host), g.id, [friend, stranger])
    assert resp.status_code == 400
    assert _code(resp) == "invite_not_friend"
    assert not GatheringInvite.objects.exists()
    assert not _outbox("gathering.invited")


def test_a_blocked_friend_cannot_be_invited(client_for, graph):
    host, friend = acct(), acct()
    graph.befriend(host, friend)  # graph's copy may lag the block
    BlockedPair.objects.create(blocker_id=friend, blocked_id=host)
    g = make_event(host)
    assert _code(_invite(client_for(host), g.id, [friend])) == "invite_not_friend"


def test_only_the_host_invites(client_for, graph):
    host, guest, friend = acct(), acct(), acct()
    graph.befriend(guest, friend)
    g = make_event(host)
    assert _invite(client_for(guest), g.id, [friend]).status_code == 403
    hidden = make_event(host, audience="invite_only")
    assert _invite(client_for(guest), hidden.id, [friend]).status_code == 404


def test_invites_fail_closed_when_graph_is_down(client_for, graph):
    host, friend = acct(), acct()
    graph.befriend(host, friend)
    g = make_event(host)
    graph.down = True
    assert _invite(client_for(host), g.id, [friend]).status_code == 503
    assert not GatheringInvite.objects.exists()


# ---- edit, cancel, delete ----------------------------------------------------------


def _patch(client, gathering_id, **data):
    return client.patch(
        reverse("gatherings:event-detail", args=[gathering_id]), data, format="json"
    )


def test_only_the_host_edits(client_for):
    g = make_event(acct())
    assert _patch(client_for(acct()), g.id, title="Mine now").status_code == 404
    assert Gathering.objects.get(id=g.id).title == "Picnic"


def test_a_title_edit_notifies_nobody(client_for):
    host = acct()
    g = make_event(host)
    services.rsvp(acct(), g.id, "going")
    assert _patch(client_for(host), g.id, title="New title").json()["data"]["title"] == "New title"
    [event] = _outbox("gathering.updated")
    assert event["changed"] == ["title"]
    assert event["notify"] == []
    assert event["recipients"] == []
    assert "New title" not in str(event)


def test_moving_the_event_notifies_going_and_interested_in_chunks(client_for, monkeypatch):
    monkeypatch.setattr(services, "RECIPIENT_CHUNK", 2)
    host = acct()
    g = make_event(host)
    going = [acct() for _ in range(2)]
    interested = acct()
    for a in going:
        services.rsvp(a, g.id, "going")
    services.rsvp(interested, g.id, "interested")
    services.rsvp(acct(), g.id, "not_going")
    GatheringReminderLog.objects.create(gathering=g, kind="24h")

    resp = _patch(client_for(host), g.id, starts_at=_future(days=4), location="Zamalek")
    assert resp.status_code == 200, resp.content
    events = _outbox("gathering.updated")
    assert [e["chunk"] for e in events] == [0, 1]
    assert {e["chunks"] for e in events} == {2}
    assert sorted(r for e in events for r in e["recipients"]) == sorted([*going, interested])
    assert events[0]["notify"] == ["location", "starts_at"]
    assert not GatheringReminderLog.objects.filter(gathering=g).exists()


def test_capacity_cannot_drop_below_people_going(client_for):
    host = acct()
    g = make_event(host, capacity=3)
    services.rsvp(acct(), g.id, "going")
    services.rsvp(acct(), g.id, "going")
    resp = _patch(client_for(host), g.id, capacity=1)
    assert _code(resp) == "capacity_below_going"
    assert _patch(client_for(host), g.id, capacity=None).json()["data"]["capacity"] is None


def test_cancel_notifies_attendees_once(client_for):
    host, going, interested = acct(), acct(), acct()
    g = make_event(host)
    services.rsvp(going, g.id, "going")
    services.rsvp(interested, g.id, "interested")
    url = reverse("gatherings:event-cancel", args=[g.id])
    assert client_for(acct()).post(url).status_code == 404
    data = client_for(host).post(url).json()["data"]
    assert data["status"] == "cancelled"
    assert _code(client_for(host).post(url)) == "event_cancelled"
    [event] = _outbox("gathering.cancelled")
    assert sorted(event["recipients"]) == sorted([going, interested])
    assert _code(_patch(client_for(host), g.id, title="x")) == "event_cancelled"


def test_delete(client_for):
    host = acct()
    g = make_event(host)
    url = reverse("gatherings:event-detail", args=[g.id])
    assert client_for(acct()).delete(url).status_code == 404
    assert client_for(host).delete(url).status_code == 204
    assert client_for(host).delete(url).status_code == 404
    assert _outbox("gathering.deleted") == [{"gathering_id": str(g.id), "host_id": host}]


# ---- reports ---------------------------------------------------------------------


def test_reports_are_deduped_and_carry_the_owner(client_for):
    host, reporter = acct(), acct()
    g = make_event(host)
    client = client_for(reporter)
    assert _report(client, g.id, "spam").status_code == 202
    assert _report(client, g.id, "scam").status_code == 202
    assert GatheringReport.objects.filter(reporter_id=reporter).count() == 1
    assert _outbox("gathering.reported") == [
        {"gathering_id": str(g.id), "reporter": reporter, "reason": "spam", "owner_id": host}
    ]


def test_a_report_reason_is_an_enum(client_for):
    g = make_event(acct())
    resp = _report(client_for(acct()), g.id, "my free text")
    assert resp.status_code == 400
    assert _code(resp) == "validation_error"  # refused before the service runs


def test_reports_share_the_post_report_throttle(client_for, settings):
    settings.POST_REPORT_RATE = "2/hour"
    client = client_for(acct())
    events = [make_event(acct()) for _ in range(3)]
    assert _report(client, events[0].id).status_code == 202
    assert _report(client, events[1].id).status_code == 202
    assert len(_outbox("gathering.reported")) == 2
    assert _report(client, events[2].id).status_code == 429


# ---- moderation ------------------------------------------------------------------


def test_moderation_remove_and_approve_round_trip(client_for):
    host, guest = acct(), acct()
    g = make_event(host)
    _actioned(g.id, "remove")
    _actioned(g.id, "remove")  # redelivered: nothing more
    assert _detail(client_for(host), g.id).status_code == 404
    assert str(g.id) not in _ids(_list(client_for(guest), "upcoming"))
    assert _rsvp(client_for(guest), g.id, "going").status_code == 404
    assert _outbox("gathering.deleted") == [
        {"gathering_id": str(g.id), "host_id": host, "by": "moderation"}
    ]

    _actioned(g.id, "approve")
    assert _detail(client_for(guest), g.id).status_code == 200
    assert str(g.id) in _ids(_list(client_for(guest), "upcoming"))
    [updated] = _outbox("gathering.updated")
    assert updated["changed"] == ["moderation_status"]


def test_other_actions_and_unknown_events_are_ignored(client_for):
    g = make_event(acct())
    _actioned(g.id, "warn")
    _actioned(acct(), "remove")
    assert Gathering.objects.get(id=g.id).moderation_status == "ok"


# ---- outbox inside the transaction -----------------------------------------------


def test_a_failed_emit_rolls_back_the_state_change(monkeypatch):
    host, guest = acct(), acct()
    g = make_event(host, capacity=2)

    def boom(*a, **k):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(services.events, "emit", boom)
    with pytest.raises(RuntimeError):
        make_event(host)
    with pytest.raises(RuntimeError):
        services.rsvp(guest, g.id, "going")
    with pytest.raises(RuntimeError):
        services.cancel_gathering(host, g.id)
    g.refresh_from_db()
    assert Gathering.objects.count() == 1
    assert (g.going_count, g.status) == (0, "scheduled")
    assert not GatheringRSVP.objects.exists()


def test_every_write_emits_in_its_own_transaction(django_capture_on_commit_callbacks):
    """``record_event`` writes the outbox row through the same connection: the row
    exists before commit (no on_commit publishing)."""
    with django_capture_on_commit_callbacks() as callbacks:
        g = make_event(acct())
    assert OutboxEvent.objects.filter(event_type="gathering.created").count() == 1
    assert Gathering.objects.filter(id=g.id).exists()
    assert len(callbacks) <= 1


# ---- blocks ----------------------------------------------------------------------


def test_a_block_drops_the_blocked_guests_rsvp_and_invite(graph):
    host, guest = acct(), acct()
    graph.befriend(host, guest)
    g = make_event(host, capacity=1)
    services.rsvp(guest, g.id, "going")
    services.invite(host, g.id, [guest])
    BlockedPair.objects.create(blocker_id=host, blocked_id=guest)
    on_user_blocked_drop_rsvps(
        EventEnvelope(
            event_type="user.blocked",
            subject_id=acct(),
            producer="graph-service",
            payload={"blocker_id": host, "blocked_id": guest},
        )
    )
    g.refresh_from_db()
    assert g.going_count == 0
    assert not GatheringRSVP.objects.exists()
    assert not GatheringInvite.objects.exists()
    services.rsvp(acct(), g.id, "going")  # the seat is free again


# ---- reminders -------------------------------------------------------------------


def _reminders(window=None):
    events = _outbox("gathering.reminder")
    return [e for e in events if window is None or e["window"] == window]


def test_reminders_go_out_once_per_window(monkeypatch):
    host, going, interested, blocked = acct(), acct(), acct(), acct()
    g = make_event(host, starts_at=timezone.now() + timedelta(hours=20))
    services.rsvp(going, g.id, "going")
    services.rsvp(interested, g.id, "interested")
    services.rsvp(blocked, g.id, "going")
    services.rsvp(acct(), g.id, "not_going")
    BlockedPair.objects.create(blocker_id=host, blocked_id=blocked)
    far = make_event(acct(), starts_at=timezone.now() + timedelta(days=3))

    assert services.send_due_reminders() == 1
    assert services.send_due_reminders() == 0  # exactly once
    [day] = _reminders("24h")
    assert day["gathering_id"] == str(g.id)
    assert sorted(day["recipients"]) == sorted([host, going, interested])
    assert not GatheringReminderLog.objects.filter(gathering=far).exists()

    # Nineteen hours later, the hour reminder: going only, once.
    later = timezone.now() + timedelta(hours=19, minutes=30)
    assert services.send_due_reminders(now=later) == 1
    assert services.send_due_reminders(now=later) == 0
    [hour] = _reminders("1h")
    assert sorted(hour["recipients"]) == sorted([host, going])
    assert GatheringReminderLog.objects.filter(gathering=g).count() == 2


def test_reminder_recipients_are_chunked(monkeypatch):
    monkeypatch.setattr(services, "RECIPIENT_CHUNK", 2)
    g = make_event(acct(), starts_at=timezone.now() + timedelta(minutes=30))
    for _ in range(4):
        services.rsvp(acct(), g.id, "going")
    assert services.send_due_reminders() == 1
    hour = _reminders("1h")
    assert [len(e["recipients"]) for e in hour] == [2, 2, 1]  # host + 4 guests
    assert {e["chunks"] for e in hour} == {3}
    assert not _reminders("24h")  # the day window had already passed


def test_moving_the_start_rearms_reminders():
    host = acct()
    g = make_event(host, starts_at=timezone.now() + timedelta(hours=10))
    services.send_due_reminders()
    assert len(_reminders("24h")) == 1
    services.edit_gathering(host, g.id, {"starts_at": timezone.now() + timedelta(hours=12)})
    services.send_due_reminders()
    assert len(_reminders("24h")) == 2


def test_cancelled_removed_and_deleted_events_get_no_reminders():
    host = acct()
    soon = timezone.now() + timedelta(hours=5)
    cancelled, removed, deleted = (make_event(host, starts_at=soon) for _ in range(3))
    services.cancel_gathering(host, cancelled.id)
    _actioned(removed.id, "remove")
    services.delete_gathering(host, deleted.id)
    assert services.send_due_reminders() == 0
    assert not GatheringReminderLog.objects.exists()


def test_mark_ended_stores_the_status():
    g = make_event(acct())
    open_ended = make_event(acct())
    Gathering.objects.filter(id=g.id).update(
        starts_at=timezone.now() - timedelta(hours=2), ends_at=timezone.now() - timedelta(hours=1)
    )
    Gathering.objects.filter(id=open_ended.id).update(starts_at=timezone.now() - timedelta(hours=4))
    assert services.mark_ended() == 2
    assert set(Gathering.objects.values_list("status", flat=True)) == {"ended"}


def test_invite_errors_are_raised_as_api_errors():
    with pytest.raises(TaraAPIError):
        services.invite(acct(), make_event(acct()).id, [])


# ---- event contracts -------------------------------------------------------------

SCHEMAS = "/opt/tara/libs/tara_events/tara_events/schemas"
_TYPES = {"string": str, "integer": int, "array": list, "null": type(None)}


def _check(payload: dict, schema: dict) -> None:
    title = schema["title"]
    assert set(schema["required"]) <= set(payload) <= set(schema["properties"]), title
    for key, value in payload.items():
        rule = schema["properties"][key]
        kinds = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
        assert isinstance(value, tuple(_TYPES[k] for k in kinds)), (title, key, value)
        if "enum" in rule:
            assert value in rule["enum"], (title, key, value)
        if rule.get("type") == "array" and "enum" in rule.get("items", {}):
            assert set(value) <= set(rule["items"]["enum"]), (title, key, value)


def test_every_gathering_event_matches_its_json_schema(graph):
    import json
    import os

    if not os.path.isdir(SCHEMAS):
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    host, friend, guest = acct(), acct(), acct()
    graph.befriend(host, friend)
    g = make_event(host, capacity=5, starts_at=timezone.now() + timedelta(hours=10))
    services.invite(host, g.id, [friend])
    services.rsvp(guest, g.id, "going")
    services.withdraw_rsvp(guest, g.id)
    services.rsvp(friend, g.id, "interested")
    services.edit_gathering(host, g.id, {"location": "Elsewhere"})
    services.send_due_reminders()
    services.report(guest, g.id, "spam")
    services.cancel_gathering(host, g.id)
    removed = make_event(host)
    _actioned(removed.id, "remove")
    _actioned(removed.id, "approve")
    services.delete_gathering(host, removed.id)

    seen = set()
    for row in OutboxEvent.objects.filter(event_type__startswith="gathering."):
        with open(f"{SCHEMAS}/{row.event_type}.v1.json", encoding="utf-8") as f:
            _check(row.payload["payload"], json.load(f))
        seen.add(row.event_type)
    assert seen == {
        "gathering.created",
        "gathering.updated",
        "gathering.cancelled",
        "gathering.deleted",
        "gathering.rsvp",
        "gathering.invited",
        "gathering.reminder",
        "gathering.reported",
    }


# ---- unfriending -----------------------------------------------------------------


def _friendship_removed(a, b, reason="unfriend"):
    from gatherings.handlers import on_friendship_removed_drop_rsvps

    on_friendship_removed_drop_rsvps(
        EventEnvelope(
            event_type="friendship.removed",
            subject_id=acct(),
            producer="graph-service",
            payload={"a": a, "b": b, "reason": reason},
            actor_id=a,
        )
    )


@pytest.fixture
def unfriended(graph):
    """Host and guest were friends; the guest answered on events of each audience."""
    host, guest = acct(), acct()
    graph.befriend(host, guest)
    friends_only = make_event(host, audience="friends", capacity=1)
    invite_only = make_event(host, audience="invite_only")
    public = make_event(host)
    services.invite(host, friends_only.id, [guest])
    services.invite(host, invite_only.id, [guest])
    for g in (friends_only, invite_only, public):
        services.rsvp(guest, g.id, "going")
    # The guest hosts too, and the host answered there.
    theirs = make_event(guest, audience="friends")
    services.rsvp(host, theirs.id, "interested")
    graph.unfriend(host, guest)
    return host, guest, friends_only, invite_only, public, theirs


def test_an_unfriend_frees_the_seat_on_friends_only_events_both_ways(client_for, graph, unfriended):
    host, guest, friends_only, invite_only, public, theirs = unfriended
    emitted = OutboxEvent.objects.count()
    _friendship_removed(host, guest)

    friends_only.refresh_from_db()
    theirs.refresh_from_db()
    assert friends_only.going_count == 0
    assert theirs.interested_count == 0
    assert not GatheringRSVP.objects.filter(gathering__in=[friends_only, theirs]).exists()
    assert not GatheringInvite.objects.filter(gathering=friends_only).exists()
    assert OutboxEvent.objects.count() == emitted  # no notification to either side

    # The seat is free for a current friend.
    friend = acct()
    graph.befriend(host, friend)
    assert _rsvp(client_for(friend), friends_only.id, "going").status_code == 200


def test_an_unfriend_leaves_invite_only_and_public_events_alone(unfriended):
    host, guest, _, invite_only, public, _ = unfriended
    _friendship_removed(host, guest, reason="unfriend")
    for g in (invite_only, public):
        g.refresh_from_db()
        assert g.going_count == 1
        assert GatheringRSVP.objects.filter(gathering=g, account_id=guest, status="going").exists()
    assert GatheringInvite.objects.filter(gathering=invite_only, invitee_id=guest).exists()
    assert services.visible_to_viewer(guest, invite_only)


def test_the_unfriend_clean_up_is_idempotent(unfriended):
    host, guest, friends_only, _, _, _ = unfriended
    _friendship_removed(host, guest)
    _friendship_removed(guest, host)  # redelivered, either order of the pair
    friends_only.refresh_from_db()
    assert friends_only.going_count == 0
    assert GatheringRSVP.objects.filter(account_id=guest).count() == 2  # invite-only, public


def test_a_stale_unfriend_after_refriending_drops_nothing(graph, unfriended):
    host, guest, friends_only, _, _, _ = unfriended
    graph.befriend(host, guest)  # friends again before the old event arrived
    _friendship_removed(host, guest)
    friends_only.refresh_from_db()
    assert friends_only.going_count == 1
    assert GatheringRSVP.objects.filter(gathering=friends_only, account_id=guest).exists()


def test_the_unfriend_clean_up_retries_while_graph_is_down(graph, unfriended):
    host, guest, friends_only, _, _, _ = unfriended
    graph.down = True
    with pytest.raises(TaraAPIError):
        _friendship_removed(host, guest)
    friends_only.refresh_from_db()
    assert friends_only.going_count == 1
    graph.down = False
    _friendship_removed(host, guest)  # the retry
    friends_only.refresh_from_db()
    assert friends_only.going_count == 0


def test_an_event_narrowed_to_invite_only_keeps_the_guest(unfriended):
    host, guest, friends_only, _, _, _ = unfriended
    Gathering.objects.filter(id=friends_only.id).update(audience="invite_only")
    _friendship_removed(host, guest)
    friends_only.refresh_from_db()
    assert friends_only.going_count == 1
