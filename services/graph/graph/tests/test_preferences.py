"""Plan 08 track 2D: mute, restrict and favorites, and their relationship.* events."""

import json
import time
import uuid
from pathlib import Path
from unittest import mock

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from graph import preferences, services
from graph.models import FavoriteRelation, MuteRelation, OutboxEvent, RestrictRelation

pytestmark = pytest.mark.django_db

SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")
EVENTS = {
    "mute": ("graph:mutes", "graph:mute", "muted", MuteRelation, "relationship.muted"),
    "restrict": (
        "graph:restricts",
        "graph:restrict",
        "restricted",
        RestrictRelation,
        "relationship.restricted",
    ),
    "favorite": (
        "graph:favorites",
        "graph:favorite",
        "favorites",
        FavoriteRelation,
        "relationship.favorited",
    ),
}
REMOVED = {
    "mute": "relationship.unmuted",
    "restrict": "relationship.unrestricted",
    "favorite": "relationship.unfavorited",
}
#: Event types the notification service turns into notifications.
NOTIFYING = {
    "friendship.requested",
    "friendship.accepted",
    "user.followed",
    "friendship.request.withdrawn",
}


def _acct() -> str:
    return str(uuid.uuid4())


def _rows(event_type: str | None = None) -> list[dict]:
    qs = OutboxEvent.objects.order_by("created_at")
    if event_type:
        qs = qs.filter(event_type=event_type)
    return [row.payload for row in qs]


def _types() -> list[str]:
    return [row["event_type"] for row in _rows()]


@pytest.mark.parametrize("kind", list(EVENTS))
def test_add_list_remove_with_one_event_each_way(client_for, kind):
    list_name, item_name, key, model, added = EVENTS[kind]
    me, other = _acct(), _acct()
    client = client_for(me)

    assert client.post(reverse(item_name, args=[other])).status_code == 204
    assert client.post(reverse(item_name, args=[other])).status_code == 204  # idempotent
    assert model.objects.filter(account_id=me, target_id=other).count() == 1
    assert client.get(reverse(list_name)).json()["data"] == {key: [other]}
    # Owner-only: another account sees its own (empty) list, never mine.
    assert client_for(other).get(reverse(list_name)).json()["data"] == {key: []}

    rows = _rows(added)
    assert len(rows) == 1
    envelope = rows[0]
    assert uuid.UUID(envelope["event_id"])
    assert envelope["subject_id"] == me and envelope["actor_id"] == me
    assert set(envelope["payload"]) == {"actor_id", "target_id", "occurred_at"}
    assert envelope["payload"]["actor_id"] == me
    assert envelope["payload"]["target_id"] == other

    assert client.delete(reverse(item_name, args=[other])).status_code == 204
    assert client.delete(reverse(item_name, args=[other])).status_code == 204
    assert not model.objects.exists()
    assert len(_rows(REMOVED[kind])) == 1
    assert APIClient().get(reverse(list_name)).status_code == 401


@pytest.mark.parametrize(
    "event_type",
    [
        "relationship.muted",
        "relationship.unmuted",
        "relationship.favorited",
        "relationship.unfavorited",
        "relationship.restricted",
        "relationship.unrestricted",
    ],
)
def test_payloads_match_their_schema(event_type):
    if not SCHEMAS.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    import jsonschema

    schema = json.loads((SCHEMAS / f"{event_type}.v1.json").read_text())
    me, other = _acct(), _acct()
    name = {"muted": "mute", "favorited": "favorite", "restricted": "restrict"}
    verb = event_type.split(".")[1].removeprefix("un")
    preferences.add(name[verb], me, other)
    if event_type.split(".")[1].startswith("un"):
        preferences.remove(name[verb], me, other)
    payload = _rows(event_type)[0]["payload"]
    jsonschema.validate(payload, schema, format_checker=jsonschema.FormatChecker())


def test_a_muted_account_is_never_notified(client_for):
    me, other = _acct(), _acct()
    services.follow(me, other)
    OutboxEvent.objects.all().delete()
    client_for(me).post(reverse("graph:mute", args=[other]))
    client_for(me).delete(reverse("graph:mute", args=[other]))
    client_for(me).post(reverse("graph:mute", args=[other]))
    types = _types()
    assert types == ["relationship.muted", "relationship.unmuted", "relationship.muted"]
    assert not set(types) & NOTIFYING
    # Muting is not unfollowing or unfriending: the edges stay.
    assert services.follows(me, other)
    # And the muted side cannot see who muted them.
    assert client_for(other).get(reverse("graph:mutes")).json()["data"] == {"muted": []}


def test_event_rolls_back_with_the_write():
    me, other = _acct(), _acct()
    with (
        mock.patch("graph.events.record_event", side_effect=RuntimeError("outbox down")),
        pytest.raises(RuntimeError),
    ):
        preferences.add("mute", me, other)
    assert not MuteRelation.objects.exists()
    assert not OutboxEvent.objects.exists()


def test_event_is_written_inside_the_transaction():
    from django.db import connection

    seen = []

    def record(model, envelope):
        seen.append(connection.in_atomic_block)
        return model.objects.create(
            id=envelope.event_id,
            event_type=envelope.event_type,
            event_version=1,
            payload=envelope.to_dict(),
            partition_key=envelope.partition_key or "",
        )

    with mock.patch("graph.events.record_event", side_effect=record):
        preferences.add("favorite", _acct(), _acct())
    assert seen == [True]


def test_flags_turn_the_events_off_but_keep_the_rows(settings):
    settings.GRAPH_EMIT_MUTE_FAVORITE_EVENTS = False
    settings.GRAPH_EMIT_RESTRICT_EVENTS = False
    me, other = _acct(), _acct()
    for kind in ("mute", "restrict"):
        assert preferences.add(kind, me, other) is True
    assert preferences.add("favorite", me, _acct()) is True
    assert MuteRelation.objects.count() == RestrictRelation.objects.count() == 1
    assert not OutboxEvent.objects.exists()


def test_mute_and_favorite_exclude_each_other():
    me, other = _acct(), _acct()
    preferences.add("favorite", me, other)
    preferences.add("mute", me, other)
    assert not FavoriteRelation.objects.exists()
    assert _types() == [
        "relationship.favorited",
        "relationship.unfavorited",
        "relationship.muted",
    ]
    OutboxEvent.objects.all().delete()
    preferences.add("favorite", me, other)
    assert not MuteRelation.objects.exists()
    assert _types() == ["relationship.unmuted", "relationship.favorited"]


def test_favorites_are_capped(client_for):
    me = _acct()
    for _ in range(preferences.MAX_FAVORITES):
        preferences.add("favorite", me, _acct())
    resp = client_for(me).post(reverse("graph:favorite", args=[_acct()]))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "favorites_limit"


def test_self_is_400_and_a_blocked_account_is_404(client_for):
    me, blocker, blocked = _acct(), _acct(), _acct()
    services.block(blocker, me)
    services.block(me, blocked)
    client = client_for(me)
    for name in ("graph:mute", "graph:restrict", "graph:favorite"):
        assert client.post(reverse(name, args=[me])).status_code == 400
        assert client.post(reverse(name, args=[blocker])).status_code == 404
        assert client.post(reverse(name, args=[blocked])).status_code == 404


def test_block_ends_favorites_both_ways_and_hides_mutes_while_it_lasts(client_for):
    me, other = _acct(), _acct()
    preferences.add("favorite", me, other)
    preferences.add("favorite", other, me)
    third = _acct()
    preferences.add("mute", me, third)
    OutboxEvent.objects.all().delete()

    services.block(me, other)
    assert not FavoriteRelation.objects.exists()
    unfav = _rows("relationship.unfavorited")
    assert sorted((r["payload"]["actor_id"], r["payload"]["target_id"]) for r in unfav) == sorted(
        [(me, other), (other, me)]
    )
    assert _types()[0] == "user.blocked"

    services.block(me, third)
    assert MuteRelation.objects.filter(account_id=me, target_id=third).exists()
    assert client_for(me).get(reverse("graph:mutes")).json()["data"] == {"muted": []}
    services.unblock(me, third)
    assert client_for(me).get(reverse("graph:mutes")).json()["data"] == {"muted": [third]}


def test_internal_preferences_snapshot_requires_a_token():
    me, muted, fav, restricted = _acct(), _acct(), _acct(), _acct()
    preferences.add("mute", me, muted)
    preferences.add("favorite", me, fav)
    preferences.add("restrict", me, restricted)
    url = reverse("preferences", args=[me])
    assert APIClient().get(url).status_code == 401

    now = int(time.time())
    token = jwt.encode(
        {"iss": "post", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert client.get(url).json()["data"] == {
        "account_id": me,
        "muted": [muted],
        "favorites": [fav],
        "restricted": [restricted],
    }
