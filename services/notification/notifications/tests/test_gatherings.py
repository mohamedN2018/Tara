"""Milestone 1.13: notifications for events (gatherings) and their deep links."""

import uuid

import pytest

from notifications import handlers, registry
from notifications.models import Notification
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _event(event_type, payload, *, subject_id=None, actor_id=None):
    return EventEnvelope(
        event_type=event_type,
        subject_id=subject_id or payload.get("gathering_id") or _acct(),
        producer="post-service",
        payload=payload,
        actor_id=actor_id,
    )


def _rows(kind: str):
    return list(Notification.objects.filter(kind=kind).order_by("created_at", "id"))


@pytest.mark.parametrize(
    "kind",
    [
        "gathering.invite",
        "gathering.reminder",
        "gathering.update",
        "gathering.cancel",
        "gathering.rsvp",
    ],
)
def test_gathering_kinds_are_registered_and_link_to_the_event(kind):
    assert registry.KINDS[kind].category == "social"
    assert registry.build_url(kind, subject_ref="gathering:g1") == "/events/g1"
    assert registry.build_url(kind, subject_ref="gathering:a/../b") == "/events/a%2F..%2Fb"


def test_only_new_rsvps_aggregate_per_event():
    assert registry.KINDS["gathering.rsvp"].aggregate == registry.PER_SUBJECT
    assert registry.KINDS["gathering.invite"].aggregate is None


def test_an_invite_notifies_each_invitee_from_the_host():
    host, one, two = _acct(), _acct(), _acct()
    gathering = _acct()
    handlers.on_gathering_invited(
        _event(
            "gathering.invited",
            {"gathering_id": gathering, "host_id": host, "invitee_ids": [one, two]},
        )
    )
    rows = _rows("gathering.invite")
    assert sorted(str(r.recipient_id) for r in rows) == sorted([one, two])
    assert {str(r.actor_id) for r in rows} == {host}
    assert {registry.url_for(r) for r in rows} == {f"/events/{gathering}"}
    assert rows[0].data == {"gathering_id": gathering}


def test_reminders_reach_every_recipient_including_the_host():
    host, guest = _acct(), _acct()
    gathering = _acct()
    payload = {
        "gathering_id": gathering,
        "host_id": host,
        "window": "1h",
        "recipients": [host, guest],
        "chunk": 0,
        "chunks": 1,
    }
    handlers.on_gathering_reminder(_event("gathering.reminder", payload))
    rows = _rows("gathering.reminder")
    assert sorted(str(r.recipient_id) for r in rows) == sorted([host, guest])
    assert all(r.data == {"gathering_id": gathering, "window": "1h"} for r in rows)


def test_an_update_notifies_only_when_time_or_place_changed():
    host, guest = _acct(), _acct()
    gathering = _acct()
    base = {"gathering_id": gathering, "host_id": host, "recipients": [guest]}
    handlers.on_gathering_updated(
        _event("gathering.updated", {**base, "changed": ["title"], "notify": []})
    )
    assert _rows("gathering.update") == []
    handlers.on_gathering_updated(
        _event("gathering.updated", {**base, "changed": ["starts_at"], "notify": ["starts_at"]})
    )
    [row] = _rows("gathering.update")
    assert str(row.recipient_id) == guest
    assert registry.url_for(row) == f"/events/{gathering}"


def test_a_cancel_notifies_attendees_but_not_the_host():
    host, guest = _acct(), _acct()
    handlers.on_gathering_cancelled(
        _event(
            "gathering.cancelled",
            {"gathering_id": _acct(), "host_id": host, "recipients": [guest, host]},
        )
    )
    assert [str(r.recipient_id) for r in _rows("gathering.cancel")] == [guest]


def test_new_rsvps_aggregate_into_one_row_for_the_host():
    host, gathering = _acct(), _acct()

    def answer(account, status, previous=None):
        handlers.on_gathering_rsvp(
            _event(
                "gathering.rsvp",
                {
                    "gathering_id": gathering,
                    "host_id": host,
                    "account_id": account,
                    "status": status,
                    "previous_status": previous,
                },
            )
        )

    first, second = _acct(), _acct()
    answer(first, "going")
    answer(second, "interested")
    answer(first, "interested", "going")  # a switch: not news
    answer(_acct(), "not_going")  # a no: not news
    answer(_acct(), None, "going")  # withdrawn: not news
    [row] = _rows("gathering.rsvp")
    assert str(row.recipient_id) == host
    assert row.actor_count == 2
    assert registry.url_for(row) == f"/events/{gathering}"


def test_a_deleted_or_removed_event_takes_its_notifications():
    host, guest, gathering = _acct(), _acct(), _acct()
    handlers.on_gathering_invited(
        _event(
            "gathering.invited",
            {"gathering_id": gathering, "host_id": host, "invitee_ids": [guest]},
        )
    )
    other = _acct()
    handlers.on_gathering_invited(
        _event(
            "gathering.invited", {"gathering_id": other, "host_id": host, "invitee_ids": [guest]}
        )
    )
    handlers.on_gathering_deleted(
        _event(
            "gathering.deleted", {"gathering_id": gathering, "host_id": host, "by": "moderation"}
        )
    )
    assert [r.subject_ref for r in Notification.objects.all()] == [f"gathering:{other}"]
