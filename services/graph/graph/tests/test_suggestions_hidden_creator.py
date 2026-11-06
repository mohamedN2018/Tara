""" "Don't recommend this creator" in graph (Tara Intelligence WP 7.5-B2): feed's
``intel.creator.hidden`` removes the creator from that viewer's people and page
suggestions; the undo restores exactly what was there. Following is untouched."""

import dataclasses
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.urls import reverse

from graph import handlers, services
from graph.models import HiddenCreator
from tara_events.envelope import EventEnvelope

from .ages import adult

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")


def _acct() -> str:
    return str(uuid.uuid4())


def _befriend(a: str, b: str) -> None:
    request = services.send_friend_request(a, b)
    services.accept_friend_request(b, str(request.id))
    adult(a, b)


def _hidden(account_id: str, creator_id: str, hidden: bool, at: datetime, event_id=None):
    payload = {
        "account_id": account_id,
        "creator_id": creator_id,
        "hidden": hidden,
        "at": at.isoformat(),
    }
    if SCHEMAS.exists():
        import jsonschema

        schema = json.loads((SCHEMAS / "intel.creator.hidden.v1.json").read_text())
        jsonschema.validate(payload, schema, format_checker=jsonschema.FormatChecker())
    envelope = EventEnvelope(
        event_type="intel.creator.hidden",
        subject_id=account_id,
        producer="feed-service",
        payload=payload,
    )
    if event_id:
        envelope = dataclasses.replace(envelope, event_id=event_id)
    handlers.on_creator_hidden(envelope)


def _people(client) -> list[str]:
    resp = client.get(reverse("graph:suggestions-people"))
    assert resp.status_code == 200
    return [r["account_id"] for r in resp.json()["data"]["results"]]


def _pages(client) -> list[str]:
    resp = client.get(reverse("graph:suggestions-pages"))
    assert resp.status_code == 200
    return [r["page_id"] for r in resp.json()["data"]["results"]]


def _page(page_id: str) -> None:
    handlers.on_page_changed(
        EventEnvelope(
            event_type="page.updated",
            payload={
                "handle": "p" + page_id[:6],
                "name": "Page " + page_id[:4],
                "owner": _acct(),
                "category": "Food",
                "location": "",
                "status": "published",
                "avatar_media_id": None,
                "deleted": False,
            },
            subject_id=page_id,
            producer="profile-service",
            occurred_at=T0.isoformat(),
        )
    )


@pytest.fixture
def pymk():
    me, bridge, a, b = _acct(), _acct(), _acct(), _acct()
    _befriend(me, bridge)
    _befriend(a, bridge)
    _befriend(b, bridge)
    return me, a, b


def test_hidden_person_leaves_people_suggestions_and_undo_restores(client_for, pymk):
    me, a, b = pymk
    before = _people(client_for(me))
    assert sorted(before) == sorted([a, b])
    _hidden(me, a, True, T0)
    assert _people(client_for(me)) == [b]
    _hidden(me, a, False, T0 + timedelta(minutes=1))
    assert _people(client_for(me)) == before


def test_only_that_viewer_is_affected(client_for, pymk):
    me, a, _b = pymk
    _hidden(me, a, True, T0)
    assert a not in _people(client_for(me))
    # Someone else who would be suggested ``a`` still is.
    viewer, bridge = _acct(), _acct()
    _befriend(viewer, bridge)
    _befriend(a, bridge)
    assert a in _people(client_for(viewer))


def test_hidden_page_leaves_page_suggestions(client_for):
    me, page_a, page_b = _acct(), _acct(), _acct()
    _page(page_a)
    _page(page_b)
    assert sorted(_pages(client_for(me))) == sorted([page_a, page_b])
    _hidden(me, page_a, True, T0)
    assert _pages(client_for(me)) == [page_b]
    _hidden(me, page_a, False, T0 + timedelta(seconds=1))
    assert sorted(_pages(client_for(me))) == sorted([page_a, page_b])


def test_following_a_hidden_creator_is_untouched(client_for):
    me, creator = _acct(), _acct()
    services.follow(me, creator)
    _hidden(me, creator, True, T0)
    assert services.follows(me, creator)


def test_newest_choice_wins_and_redelivery_is_harmless(client_for, pymk):
    me, a, _b = pymk
    _hidden(me, a, True, T0 + timedelta(minutes=5))
    _hidden(me, a, False, T0)  # an older undo arriving late
    assert a not in _people(client_for(me))
    _hidden(me, a, True, T0 + timedelta(minutes=5))  # redelivery
    assert HiddenCreator.objects.filter(account_id=me).count() == 1


def test_malformed_event_is_dropped():
    handlers.on_creator_hidden(
        EventEnvelope(
            event_type="intel.creator.hidden",
            subject_id="x",
            producer="feed-service",
            payload={"account_id": "nope", "creator_id": _acct(), "hidden": True, "at": "x"},
        )
    )
    assert HiddenCreator.objects.count() == 0
