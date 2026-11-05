"""A member's message to Tara Support tells the support team (fix round 3):
the event's ``team`` lists who answers the support inbox, from identity."""

import uuid

import pytest
import requests
from django.core.cache import cache
from django.urls import reverse

from chat import identity_client, services
from chat.models import Message, OutboxEvent

pytestmark = pytest.mark.django_db

# The real lookup, kept before the autouse stub (conftest) replaces it.
_REAL_SUPPORT_STAFF = identity_client.support_staff


def _acct() -> str:
    return str(uuid.uuid4())


def _last_payload() -> dict:
    row = OutboxEvent.objects.filter(event_type="message.created").latest("created_at")
    return row.payload["payload"]


def test_a_support_message_lists_the_support_team(identity):
    member, mod, admin = _acct(), _acct(), _acct()
    identity.staff = [mod, admin]
    conv = services.open_support_conversation(member)
    services.send_message(member, str(conv.id), body="My account is locked")
    payload = _last_payload()
    assert payload["recipients"] == [member]  # staff are never members
    assert payload["team"] == {
        "kind": "support",
        "page_id": None,
        "name": "",
        "recipients": sorted([mod, admin]),
    }


def test_a_staffer_writing_to_support_is_not_told_of_their_own_message(identity):
    staffer, other = _acct(), _acct()
    identity.staff = [staffer, other]
    conv = services.open_support_conversation(staffer)
    services.send_message(staffer, str(conv.id), body="testing")
    assert _last_payload()["team"]["recipients"] == [other]


def test_the_support_teams_reply_tells_nobody_on_it(client_for, identity):
    member = _acct()
    staff_id = _acct()
    identity.staff = [staff_id]
    conv = services.open_support_conversation(member)
    services.send_message(member, str(conv.id), body="help")
    calls = identity.calls
    resp = client_for(staff_id, roles=["moderator"]).post(
        reverse("chat:team-messages", args=[conv.id]), {"body": "On it"}, format="json"
    )
    assert resp.status_code == 201
    payload = _last_payload()
    assert "team" not in payload
    assert payload["sender_as"]["kind"] == "support"
    assert identity.calls == calls  # a reply does not ask who the team is


def test_identity_down_keeps_the_message_and_only_loses_the_notice(identity):
    member = _acct()
    identity.staff = [_acct()]
    identity.down = True
    conv = services.open_support_conversation(member)
    services.send_message(member, str(conv.id), body="hello?")
    assert _last_payload()["team"]["recipients"] == []
    assert Message.objects.filter(conversation=conv, body="hello?").exists()


def test_the_flag_turns_the_support_notice_off(identity, settings):
    settings.CHAT_NOTIFY_SUPPORT_TEAM = False
    member = _acct()
    identity.staff = [_acct()]
    conv = services.open_support_conversation(member)
    services.send_message(member, str(conv.id), body="hi")
    assert _last_payload()["team"]["recipients"] == []
    assert identity.calls == 0


def test_page_and_direct_messages_never_ask_identity(identity, client_for, profile):
    owner, visitor = _acct(), _acct()
    page = profile.add_page(team={owner: "owner"})
    conv = services.open_page_conversation(visitor, page)
    services.send_message(visitor, str(conv.id), body="hi page")
    assert _last_payload()["team"]["recipients"] == [owner]
    assert identity.calls == 0


# ---- the client itself --------------------------------------------------------


class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._data


@pytest.fixture
def real_client(monkeypatch, identity):
    # Undo the autouse stub for these tests only.
    monkeypatch.setattr("chat.identity_client.support_staff", _REAL_SUPPORT_STAFF)
    cache.clear()
    yield identity_client
    cache.clear()


def test_the_client_signs_with_chats_own_secret_and_caches(real_client, monkeypatch, settings):
    import jwt

    settings.CHAT_IDENTITY_SECRET = "chat-identity-secret-only-chat-holds-0123456789"
    seen = []

    def fake_get(url, params, headers, timeout):
        seen.append((url, params, headers))
        return _Resp(200, {"data": {"capability": params["capability"], "account_ids": ["b", "a"]}})

    monkeypatch.setattr("chat.identity_client.requests.get", fake_get)
    assert real_client.support_staff() == ["a", "b"]
    assert real_client.support_staff() == ["a", "b"]
    assert len(seen) == 1  # cached
    url, params, headers = seen[0]
    assert url.endswith("/internal/v1/capability-holders/")
    assert params == {"capability": "moderation.case.view"}
    token = headers["Authorization"].split()[1]
    claims = jwt.decode(
        token,
        settings.CHAT_IDENTITY_SECRET,
        algorithms=["HS256"],
        audience="identity.roles",
    )
    assert claims["iss"] == "chat"


def test_the_client_fails_soft(real_client, monkeypatch, settings):
    settings.CHAT_IDENTITY_SECRET = "chat-identity-secret-only-chat-holds-0123456789"
    monkeypatch.setattr("chat.identity_client.requests.get", lambda *a, **k: _Resp(401, {}))
    assert real_client.support_staff() == []
    # A failure is not cached: the next message asks again.
    monkeypatch.setattr(
        "chat.identity_client.requests.get",
        lambda *a, **k: _Resp(200, {"data": {"account_ids": ["x"]}}),
    )
    assert real_client.support_staff() == ["x"]


def test_no_secret_never_calls_identity(real_client, monkeypatch, settings):
    settings.CHAT_IDENTITY_SECRET = ""

    def boom(*a, **k):
        raise AssertionError("identity must not be called without the secret")

    monkeypatch.setattr("chat.identity_client.requests.get", boom)
    assert real_client.support_staff() == []
