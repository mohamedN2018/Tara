"""Intelligence WP 3.3 (rule E11, D14): an account under a moderation
``restrict`` or ``shadow`` leaves people suggestions but keeps its fan-out,
both as an author and as a recipient. ``reinstate`` (moderation WP 3.3b) lifts
it; the newest event wins."""

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from graph import handlers, services
from graph.models import AccountRef
from tara_events.envelope import EventEnvelope

from .ages import adult

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _acct() -> str:
    return str(uuid.uuid4())


def _befriend(a: str, b: str) -> None:
    request = services.send_friend_request(a, b)
    services.accept_friend_request(b, str(request.id))


def _actioned(target_id: str, action: str, at: datetime, target_type: str = "user") -> None:
    case_id = _acct()
    handlers.on_moderation_actioned(
        EventEnvelope(
            event_type="moderation.actioned",
            subject_id=case_id,
            producer="moderation-service",
            payload={
                "case_id": case_id,
                "target_type": target_type,
                "target_id": target_id,
                "action": action,
                "owner_id": target_id,
            },
            occurred_at=at.isoformat(),
        )
    )


def _people(client) -> list[str]:
    resp = client.get(reverse("graph:suggestions-people"))
    assert resp.status_code == 200
    return [r["account_id"] for r in resp.json()["data"]["results"]]


def _fanout(author: str) -> dict:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "feed", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    resp = client.get(reverse("fanout-audience", args=[author]))
    assert resp.status_code == 200
    return resp.json()["data"]


@pytest.fixture
def pymk():
    me, bridge, fof, fan = _acct(), _acct(), _acct(), _acct()
    _befriend(me, bridge)
    _befriend(fof, bridge)
    services.follow(fan, me)
    adult(fof, fan)  # E9b: only adults are suggested (R4)
    return me, fof, fan


@pytest.mark.parametrize("action", ["restrict", "shadow"])
def test_a_restricted_account_leaves_pymk_until_reinstated(client_for, pymk, action):
    me, fof, fan = pymk
    _actioned(fof, action, T0)
    _actioned(fan, action, T0)
    assert _people(client_for(me)) == []

    _actioned(fof, "reinstate", T0 + timedelta(minutes=1))
    _actioned(fan, "reinstate", T0 + timedelta(minutes=1))
    assert set(_people(client_for(me))) == {fof, fan}


@pytest.mark.parametrize("action", ["restrict", "shadow"])
def test_a_restricted_account_keeps_its_fanout(action):
    author, follower, friend = _acct(), _acct(), _acct()
    services.follow(follower, author)
    _befriend(author, friend)
    _actioned(author, action, T0)  # as the author
    _actioned(follower, action, T0)  # as a recipient
    data = _fanout(author)
    assert data["recipients"] == sorted([follower, friend])


@pytest.mark.parametrize("action", ["warn", "dismiss", "remove", "approve"])
def test_other_actions_change_nothing(client_for, pymk, action):
    me, fof, fan = pymk
    _actioned(fof, action, T0)
    assert set(_people(client_for(me))) == {fof, fan}
    assert not AccountRef.objects.filter(account_id=fof).exclude(restriction="").exists()


def test_restrict_on_another_target_type_changes_nothing(client_for, pymk):
    me, fof, fan = pymk
    _actioned(fof, "restrict", T0, target_type="page")
    assert set(_people(client_for(me))) == {fof, fan}


def test_an_older_redelivered_restriction_does_not_override_a_reinstate():
    account = _acct()
    _actioned(account, "reinstate", T0 + timedelta(minutes=5))
    _actioned(account, "shadow", T0)  # late, older
    assert AccountRef.objects.get(account_id=account).restriction == ""

    _actioned(account, "restrict", T0 + timedelta(minutes=6))
    row = AccountRef.objects.get(account_id=account)
    assert row.restriction == "restrict"
    assert row.restriction_case_id is not None


def test_a_malformed_target_is_ignored():
    _actioned("not-a-uuid", "shadow", T0)
    assert not AccountRef.objects.exclude(restriction="").exists()
