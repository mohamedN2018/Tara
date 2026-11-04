"""Administrative notices (system.notice): staff send, notification delivers (track T7)."""

import uuid

import pytest
from django.urls import reverse

from adminsvc import identity_client
from adminsvc.models import AuditEntry, OutboxEvent, SystemNotice

pytestmark = pytest.mark.django_db

CAP = "admin.notices.send"


def _acct() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def known(monkeypatch):
    """Accounts identity knows; summaries returns only those."""
    accounts: set[str] = set()

    def summaries(ids):
        return [{"account_id": i} for i in ids if i in accounts]

    monkeypatch.setattr(identity_client, "account_summaries", summaries)
    return accounts


def test_sending_a_notice_records_it_audits_it_and_emits_the_event(client_for, known):
    staff, a, b = _acct(), _acct(), _acct()
    known.update({a, b})
    resp = client_for(staff, caps=[CAP]).post(
        reverse("adminsvc:notices"),
        {"recipient_ids": [a, b, a], "body": "  Please update your page details.  "},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["recipient_count"] == 2 and data["body"] == "Please update your page details."

    notice = SystemNotice.objects.get()
    assert notice.recipient_ids == [a, b]
    entry = AuditEntry.objects.get(action="system_notice.sent")
    assert str(entry.actor_id) == staff and entry.detail == {"recipient_count": 2}
    event = OutboxEvent.objects.get(event_type="system.notice")
    assert event.payload["payload"] == {
        "notice_id": str(notice.id),
        "recipients": [a, b],
        "body": "Please update your page details.",
    }
    assert event.payload["actor_id"] == staff

    listed = client_for(staff, caps=[CAP]).get(reverse("adminsvc:notices")).json()["data"]
    assert [n["id"] for n in listed] == [str(notice.id)]


def test_unknown_recipients_refuse_the_whole_notice(client_for, known):
    a = _acct()
    known.add(a)
    resp = client_for(_acct(), caps=[CAP]).post(
        reverse("adminsvc:notices"), {"recipient_ids": [a, _acct()], "body": "hi"}, format="json"
    )
    assert resp.status_code == 400
    assert not SystemNotice.objects.exists()
    assert not OutboxEvent.objects.filter(event_type="system.notice").exists()


@pytest.mark.parametrize(
    "payload",
    [
        {"recipient_ids": [], "body": "hi"},
        {"recipient_ids": [str(uuid.uuid4()) for _ in range(51)], "body": "hi"},
        {"recipient_ids": ["not-a-uuid"], "body": "hi"},
        {"recipient_ids": [str(uuid.uuid4())], "body": "x" * 301},
        {"recipient_ids": [str(uuid.uuid4())], "body": "   "},
    ],
)
def test_invalid_notices_are_refused(client_for, known, payload):
    known.update(payload["recipient_ids"])
    resp = client_for(_acct(), caps=[CAP]).post(reverse("adminsvc:notices"), payload, format="json")
    assert resp.status_code == 400


def test_notices_need_the_capability(client_for, known):
    a = _acct()
    known.add(a)
    url = reverse("adminsvc:notices")
    # The locked admin role holds every capability, this one included. Checked
    # first: a refused request marks the (test-wide) transaction for rollback,
    # because the view runs outside ATOMIC_REQUESTS.
    assert client_for(_acct(), roles=["admin"]).get(url).status_code == 200
    assert client_for(_acct()).get(url).status_code == 403
    assert (
        client_for(_acct(), roles=["moderator"])
        .post(url, {"recipient_ids": [a], "body": "hi"}, format="json")
        .status_code
        == 403
    )


def test_the_emission_can_be_held(client_for, known, settings):
    settings.ADMIN_EMIT_SYSTEM_NOTICES = False
    a = _acct()
    known.add(a)
    resp = client_for(_acct(), caps=[CAP]).post(
        reverse("adminsvc:notices"), {"recipient_ids": [a], "body": "hi"}, format="json"
    )
    assert resp.status_code == 201
    assert SystemNotice.objects.exists()
    assert not OutboxEvent.objects.filter(event_type="system.notice").exists()
