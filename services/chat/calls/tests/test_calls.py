"""Calls (roadmap 3.7, 3.8): who may call, tokens, the state machine, ring
timeouts, kicks, webhooks, events and call-log messages."""

import base64
import hashlib
import json
import threading
import time
import uuid
from datetime import timedelta

import jwt
import pytest
from chat import services as chat
from chat.models import BlockedPair, Message, OutboxEvent
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from livekit import api

from calls import services as calls
from calls.models import Call, CallParticipant, LiveKitWebhookEvent
from calls.tests.conftest import KEY, SECRET

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _events(event_type):
    return [e.payload["payload"] for e in OutboxEvent.objects.filter(event_type=event_type)]


def _dm():
    a, b = _acct(), _acct()
    return a, b, chat.create_or_get_dm(a, b)


def _group(size=3):
    owner = _acct()
    others = [_acct() for _ in range(size - 1)]
    return owner, others, chat.create_group(owner, others, "team")


def _start(client, conversation, kind="audio", **extra):
    return client.post(
        reverse("calls:start", args=[conversation.id]), {"kind": kind, **extra}, format="json"
    )


def _call_logs(conversation):
    return list(
        Message.objects.filter(conversation=conversation, type="system")
        .order_by("created_at")
        .values_list("body", flat=True)
    )


# ---- availability -----------------------------------------------------------------


def test_config_reports_whether_calls_are_on(client_for, settings):
    me = _acct()
    on = client_for(me).get(reverse("calls:config")).json()["data"]
    assert on == {"enabled": True, "ring_timeout_s": 45, "max_participants": 16}
    settings.LIVEKIT_API_SECRET = ""
    assert client_for(me).get(reverse("calls:config")).json()["data"]["enabled"] is False


def test_without_keys_every_call_endpoint_answers_503(client_for, settings):
    a, b, conv = _dm()
    call_id = _start(client_for(a), conv).json()["data"]["call_id"]
    settings.LIVEKIT_API_KEY = ""
    c = client_for(a)
    responses = [
        _start(c, conv),
        c.get(reverse("calls:active", args=[conv.id])),
        c.post(reverse("calls:join", args=[call_id])),
        c.post(reverse("calls:decline", args=[call_id])),
        c.post(reverse("calls:end", args=[call_id])),
    ]
    for r in responses:
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "calls_unavailable"


# ---- who may call ------------------------------------------------------------------------


def test_a_non_member_gets_404_and_starts_nothing(client_for):
    _a, _b, conv = _dm()
    r = _start(client_for(_acct()), conv)
    assert r.status_code == 404
    assert not Call.objects.exists()


@pytest.mark.parametrize("blocker", ["caller", "callee"])
def test_a_blocked_dm_cannot_call_either_way(client_for, blocker):
    a, b, conv = _dm()
    pair = (a, b) if blocker == "caller" else (b, a)
    BlockedPair.objects.create(blocker_id=pair[0], blocked_id=pair[1])
    r = _start(client_for(a), conv)
    assert r.status_code == 404  # hidden, as everywhere in Tara
    assert not Call.objects.exists()


def test_an_unanswered_message_request_cannot_ring_either_way(client_for, graph):
    a, b = _acct(), _acct()
    graph.make_strangers(a, b)
    conv = chat.create_or_get_dm(a, b)
    for who in (a, b):
        r = _start(client_for(who), conv)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "message_request"
    assert not Call.objects.exists()
    chat.accept_request(b, str(conv.id))
    assert _start(client_for(a), conv).status_code == 201


def test_a_blocked_callee_cannot_join_an_existing_call(client_for):
    a, b, conv = _dm()
    call_id = _start(client_for(a), conv).json()["data"]["call_id"]
    BlockedPair.objects.create(blocker_id=b, blocked_id=a)
    assert client_for(b).post(reverse("calls:join", args=[call_id])).status_code == 404
    assert client_for(b).get(reverse("calls:active", args=[conv.id])).status_code == 404


def test_kind_must_be_audio_or_video(client_for):
    a, _b, conv = _dm()
    assert _start(client_for(a), conv, kind="screen").status_code == 400


def test_group_calls_do_not_ring_members_blocked_with_the_caller(client_for):
    owner, (x, y), conv = _group()
    BlockedPair.objects.create(blocker_id=y, blocked_id=owner)
    _start(client_for(owner), conv)
    (started,) = _events("call.started")
    assert started["recipients"] == [x]


# ---- tokens ------------------------------------------------------------------------------


def test_the_token_is_for_the_server_room_only_with_the_caller_as_identity(client_for):
    a, _b, conv = _dm()
    before = int(time.time())
    r = _start(client_for(a), conv, room="attacker-room", identity="someone-else")
    assert r.status_code == 201
    data = r.json()["data"]
    call = Call.objects.get(id=data["call_id"])
    assert data["room"] == call.room != "attacker-room"
    assert call.room.startswith(f"call_{call.id.hex}_") and len(call.room) > 50
    assert data["url"] == "ws://livekit.test"
    claims = jwt.decode(data["token"], SECRET, algorithms=["HS256"], issuer=KEY)
    assert claims["sub"] == a
    assert claims["video"]["room"] == call.room
    assert claims["video"]["roomJoin"] is True
    for grant in ("roomAdmin", "roomCreate", "roomList", "roomRecord"):
        assert not claims["video"].get(grant)
    assert claims["exp"] - before <= 600 + 2
    assert claims["exp"] - claims["nbf"] <= 600


def test_the_token_ttl_is_capped_at_ten_minutes(client_for, settings):
    settings.CALL_TOKEN_TTL_SECONDS = 3600
    a, _b, conv = _dm()
    token = _start(client_for(a), conv).json()["data"]["token"]
    claims = jwt.decode(token, SECRET, algorithms=["HS256"], issuer=KEY)
    assert claims["exp"] - claims["nbf"] <= 600


def test_each_participant_gets_their_own_identity(client_for):
    a, b, conv = _dm()
    call_id = _start(client_for(a), conv).json()["data"]["call_id"]
    token = client_for(b).post(reverse("calls:join", args=[call_id])).json()["data"]["token"]
    assert jwt.decode(token, SECRET, algorithms=["HS256"], issuer=KEY)["sub"] == b


# ---- the state machine -----------------------------------------------------------------


def test_starting_rings_the_callee_and_answering_makes_it_active(client_for):
    a, b, conv = _dm()
    r = _start(client_for(a), conv, kind="video")
    assert r.status_code == 201
    call = r.json()["data"]["call"]
    assert call["state"] == "ringing" and call["kind"] == "video"
    assert {p["account_id"]: p["state"] for p in call["participants"]} == {
        a: "accepted",
        b: "ringing",
    }
    (started,) = _events("call.started")
    assert started["recipients"] == [b] and started["initiator"] == a
    assert started["kind"] == "video" and started["conversation_type"] == "dm"

    joined = client_for(b).post(reverse("calls:join", args=[call["id"]]))
    assert joined.status_code == 200
    assert joined.json()["data"]["call"]["state"] == "active"
    (answered,) = _events("call.answered")
    assert answered["account"] == b and set(answered["recipients"]) == {a, b}


def test_starting_again_joins_the_live_call(client_for):
    a, b, conv = _dm()
    first = _start(client_for(a), conv).json()["data"]
    again = _start(client_for(b), conv, kind="video")
    assert again.status_code == 200
    assert again.json()["data"]["call_id"] == first["call_id"]
    assert Call.objects.count() == 1
    assert Call.objects.get().state == "active"  # the callee "starting" answered it


def test_a_rejoin_gets_a_fresh_token_without_a_second_answer(client_for):
    a, b, conv = _dm()
    call_id = _start(client_for(a), conv).json()["data"]["call_id"]
    client_for(b).post(reverse("calls:join", args=[call_id]))
    again = client_for(b).post(reverse("calls:join", args=[call_id]))
    assert again.status_code == 200
    assert len(_events("call.answered")) == 1


def test_declining_a_dm_call_ends_it_with_a_log(client_for):
    a, b, conv = _dm()
    call_id = _start(client_for(a), conv).json()["data"]["call_id"]
    r = client_for(b).post(reverse("calls:decline", args=[call_id]))
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "ended"
    assert r.json()["data"]["end_reason"] == "declined"
    assert _events("call.declined")[0]["account"] == b
    (ended,) = _events("call.ended")
    assert ended["reason"] == "declined" and ended["duration_s"] == 0
    assert _call_logs(conv) == ["call:declined:audio"]
    # Repeating it changes nothing.
    client_for(b).post(reverse("calls:decline", args=[call_id]))
    assert len(_events("call.ended")) == 1


def test_the_caller_hanging_up_while_ringing_is_a_missed_call(client_for):
    a, b, conv = _dm()
    call_id = _start(client_for(a), conv).json()["data"]["call_id"]
    r = client_for(a).post(reverse("calls:end", args=[call_id]))
    assert r.json()["data"]["state"] == "missed"
    (missed,) = _events("call.missed")
    assert missed["missed"] == [b] and missed["final"] is True and missed["reason"] == "cancelled"
    assert _call_logs(conv) == ["call:missed:audio"]


def test_hanging_up_an_answered_call_logs_its_duration(
    client_for, lk, django_capture_on_commit_callbacks
):
    a, b, conv = _dm()
    call_id = _start(client_for(a), conv, kind="video").json()["data"]["call_id"]
    client_for(b).post(reverse("calls:join", args=[call_id]))
    Call.objects.filter(id=call_id).update(answered_at=timezone.now() - timedelta(seconds=192))
    with django_capture_on_commit_callbacks(execute=True):
        r = client_for(b).post(reverse("calls:end", args=[call_id]))
    data = r.json()["data"]
    assert data["state"] == "ended" and data["end_reason"] == "hangup"
    assert 192 <= data["duration_s"] <= 194
    (ended,) = _events("call.ended")
    assert ended["duration_s"] == data["duration_s"] and set(ended["recipients"]) == {a, b}
    assert _call_logs(conv) == [f"call:ended:video:{data['duration_s']}"]
    assert Call.objects.get(id=call_id).room in lk.deleted
    # Ended calls cannot be joined; ending again is a no-op.
    assert client_for(a).post(reverse("calls:join", args=[call_id])).status_code == 409
    assert client_for(a).post(reverse("calls:end", args=[call_id])).status_code == 200
    assert len(_events("call.ended")) == 1


def test_call_logs_are_system_messages_outside_search_and_tell_members(client_for):
    a, b, conv = _dm()
    call_id = _start(client_for(a), conv).json()["data"]["call_id"]
    client_for(a).post(reverse("calls:end", args=[call_id]))
    log = Message.objects.get(conversation=conv, type="system")
    assert log.sender_id == uuid.UUID(a) and log.body_norm == ""
    created = [e for e in _events("message.created") if e["type"] == "system"]
    assert len(created) == 1 and set(created[0]["recipients"]) == {a, b}
    assert client_for(b).get(reverse("chat:message-search"), {"q": "call"}).json()["data"] == []


def test_active_endpoint_shows_the_live_call_to_members_only(client_for):
    a, b, conv = _dm()
    assert client_for(a).get(reverse("calls:active", args=[conv.id])).json()["data"] is None
    call_id = _start(client_for(a), conv).json()["data"]["call_id"]
    live = client_for(b).get(reverse("calls:active", args=[conv.id])).json()["data"]
    assert live["id"] == call_id and "room" not in live
    assert client_for(_acct()).get(reverse("calls:active", args=[conv.id])).status_code == 404
    assert client_for(_acct()).post(reverse("calls:join", args=[call_id])).status_code == 404


def test_events_are_written_in_the_same_transaction(client_for, monkeypatch):
    a, _b, conv = _dm()

    def boom(*args, **kwargs):
        raise RuntimeError("after the event")

    monkeypatch.setattr("calls.services._grant", boom)
    with pytest.raises(RuntimeError):
        calls.start_call(a, conv.id, "audio")
    assert not Call.objects.exists()
    assert not OutboxEvent.objects.filter(event_type="call.started").exists()


# ---- one live call per conversation --------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_starts_make_one_call():
    a, b, conv = _dm()
    barrier = threading.Barrier(2)
    results, errors = [], []

    def start(who):
        try:
            barrier.wait(5)
            grant, created = calls.start_call(who, conv.id, "audio")
            results.append((grant["call_id"], created))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=start, args=(who,)) for who in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert errors == []
    assert len({call_id for call_id, _ in results}) == 1
    assert sorted(created for _, created in results) == [False, True]
    assert Call.objects.count() == 1


def test_the_database_refuses_a_second_live_call():
    from django.db import IntegrityError, transaction

    a, _b, conv = _dm()
    calls.start_call(a, conv.id, "audio")
    with pytest.raises(IntegrityError), transaction.atomic():
        Call.objects.create(conversation=conv, room="call_x", initiator_id=a)


# ---- ring timeout ------------------------------------------------------------------------


def test_an_unanswered_call_becomes_missed_after_45_seconds_exactly_once(client_for):
    a, b, conv = _dm()
    call_id = _start(client_for(a), conv, kind="video").json()["data"]["call_id"]
    assert calls.sweep_ringing(timezone.now() + timedelta(seconds=30)) == 0
    assert Call.objects.get(id=call_id).state == "ringing"
    later = timezone.now() + timedelta(seconds=46)
    assert calls.sweep_ringing(later) == 1
    assert calls.sweep_ringing(later) == 0
    call = Call.objects.get(id=call_id)
    assert call.state == "missed" and call.end_reason == "timeout"
    (missed,) = _events("call.missed")
    assert missed["missed"] == [b] and missed["final"] is True
    assert _call_logs(conv) == ["call:missed:video"]
    assert CallParticipant.objects.get(call=call, account_id=b).state == "missed"


def test_group_members_who_never_answer_miss_it_while_the_call_goes_on(client_for):
    owner, (x, y), conv = _group()
    call_id = _start(client_for(owner), conv).json()["data"]["call_id"]
    client_for(x).post(reverse("calls:join", args=[call_id]))
    assert calls.sweep_ringing(timezone.now() + timedelta(seconds=46)) == 1
    assert Call.objects.get(id=call_id).state == "active"
    (missed,) = _events("call.missed")
    assert missed["missed"] == [y] and missed["final"] is False and missed["recipients"] == [y]
    assert _call_logs(conv) == []  # the call itself was answered


def test_the_sweeper_purges_old_webhook_ids():
    LiveKitWebhookEvent.objects.create(event_id="old", event="participant_joined")
    LiveKitWebhookEvent.objects.filter(event_id="old").update(
        received_at=timezone.now() - timedelta(days=3)
    )
    calls.sweep_ringing()
    assert not LiveKitWebhookEvent.objects.filter(event_id="old").exists()


# ---- groups -------------------------------------------------------------------------------


def test_a_group_call_goes_on_until_the_last_one_leaves(
    client_for, lk, django_capture_on_commit_callbacks
):
    owner, (x, y), conv = _group()
    call_id = _start(client_for(owner), conv).json()["data"]["call_id"]
    client_for(x).post(reverse("calls:join", args=[call_id]))
    client_for(y).post(reverse("calls:decline", args=[call_id]))
    assert Call.objects.get(id=call_id).state == "active"  # one decline in a group
    with django_capture_on_commit_callbacks(execute=True):
        left = client_for(owner).post(reverse("calls:end", args=[call_id])).json()["data"]
    assert left["state"] == "active"
    room = Call.objects.get(id=call_id).room
    assert lk.removed == [(room, owner)]
    with django_capture_on_commit_callbacks(execute=True):
        last = client_for(x).post(reverse("calls:end", args=[call_id])).json()["data"]
    assert last["state"] == "ended"
    assert room in lk.deleted
    assert _call_logs(conv)[-1].startswith("call:ended:audio:")


def test_a_group_where_everyone_declines_ends_declined(client_for):
    owner, (x, y), conv = _group()
    call_id = _start(client_for(owner), conv).json()["data"]["call_id"]
    client_for(x).post(reverse("calls:decline", args=[call_id]))
    assert Call.objects.get(id=call_id).state == "ringing"
    client_for(y).post(reverse("calls:decline", args=[call_id]))
    call = Call.objects.get(id=call_id)
    assert call.state == "ended" and call.end_reason == "declined"


def test_a_member_added_later_can_join_and_the_call_is_capped(client_for, settings):
    owner, (x,), conv = _group(size=2)
    call_id = _start(client_for(owner), conv).json()["data"]["call_id"]
    late = _acct()
    chat.add_members(owner, str(conv.id), [late])
    assert client_for(late).post(reverse("calls:join", args=[call_id])).status_code == 200
    settings.CALL_MAX_PARTICIPANTS = 2
    full = client_for(x).post(reverse("calls:join", args=[call_id]))
    assert full.status_code == 409 and full.json()["error"]["code"] == "call_full"


# ---- kicks on removal and block ------------------------------------------------------------


def test_removing_a_member_kicks_them_from_the_call(
    client_for, lk, django_capture_on_commit_callbacks
):
    owner, (x, y), conv = _group()
    call_id = _start(client_for(owner), conv).json()["data"]["call_id"]
    client_for(x).post(reverse("calls:join", args=[call_id]))
    with django_capture_on_commit_callbacks(execute=True):
        chat.remove_member(owner, str(conv.id), x)
    call = Call.objects.get(id=call_id)
    assert lk.removed == [(call.room, x)]
    assert call.state == "active"  # the caller is still there
    assert CallParticipant.objects.get(call=call, account_id=x).state == "left"
    revoked = [e for e in _events("call.ended") if e["reason"] == "revoked"]
    assert revoked and revoked[0]["recipients"] == [x]
    # The removed member cannot come back with the API either.
    assert client_for(x).post(reverse("calls:join", args=[call_id])).status_code == 404


def test_a_block_ends_a_dm_call_and_closes_the_room(
    client_for, lk, django_capture_on_commit_callbacks
):
    a, b, conv = _dm()
    call_id = _start(client_for(a), conv).json()["data"]["call_id"]
    client_for(b).post(reverse("calls:join", args=[call_id]))
    with django_capture_on_commit_callbacks(execute=True):
        BlockedPair.objects.create(blocker_id=b, blocked_id=a)
        chat.revoke_pair_subscriptions(b, a)
    call = Call.objects.get(id=call_id)
    assert call.state == "ended"
    assert call.room in lk.deleted
    # The reason does not tell the blocked side about the block.
    assert _events("call.ended")[0]["reason"] == "hangup"


# ---- LiveKit webhooks ---------------------------------------------------------------------


def _webhook(client, event: dict, *, secret=SECRET, tamper=False):
    body = json.dumps(event)
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    token = api.AccessToken(KEY, secret).with_sha256(digest).to_jwt()
    if tamper:
        body = body.replace("participant", "participant ", 1)
    return client.post(
        reverse("calls_internal:livekit-webhook"),
        data=body,
        content_type="application/webhook+json",
        HTTP_AUTHORIZATION=token,
    )


def _wh_event(kind, room, identity=None, event_id=None, at=None):
    event = {
        "event": kind,
        "id": event_id or f"EV_{uuid.uuid4().hex[:12]}",
        "createdAt": str(int(at or time.time())),
        "room": {"name": room},
    }
    if identity is not None:
        event["participant"] = {"identity": identity, "sid": "PA_x"}
    return event


def _answered_dm(client_for):
    a, b, conv = _dm()
    call_id = _start(client_for(a), conv).json()["data"]["call_id"]
    client_for(b).post(reverse("calls:join", args=[call_id]))
    return a, b, conv, Call.objects.get(id=call_id)


def test_a_signed_webhook_marks_the_participant_in_the_room(client, client_for):
    a, _b, _conv, call = _answered_dm(client_for)
    r = _webhook(client, _wh_event("participant_joined", call.room, a, event_id="EV_one"))
    assert r.status_code == 200 and r.json()["data"]["outcome"] == "ok"
    assert CallParticipant.objects.get(call=call, account_id=a).in_room
    replay = _webhook(client, _wh_event("participant_joined", call.room, a, event_id="EV_one"))
    assert replay.json()["data"]["outcome"] == "duplicate"


@pytest.mark.parametrize("mode", ["wrong_secret", "tampered_body", "no_header"])
def test_an_invalid_webhook_signature_is_rejected(client, client_for, mode):
    a, _b, _conv, call = _answered_dm(client_for)
    event = _wh_event("participant_left", call.room, a)
    if mode == "no_header":
        r = client.post(
            reverse("calls_internal:livekit-webhook"),
            data=json.dumps(event),
            content_type="application/webhook+json",
        )
    else:
        r = _webhook(
            client,
            event,
            secret="another-secret-0123456789abcdef0123" if mode == "wrong_secret" else SECRET,
            tamper=mode == "tampered_body",
        )
    assert r.status_code == 401
    assert Call.objects.get(id=call.id).state == "active"
    assert not LiveKitWebhookEvent.objects.exists()


def test_a_dm_participant_crashing_out_ends_the_call(client, client_for):
    a, b, conv, call = _answered_dm(client_for)
    now = time.time()
    _webhook(client, _wh_event("participant_joined", call.room, a, at=now - 5))
    _webhook(client, _wh_event("participant_joined", call.room, b, at=now - 4))
    _webhook(client, _wh_event("participant_left", call.room, b, at=now))
    call.refresh_from_db()
    assert call.state == "ended" and call.end_reason == "left"
    assert _call_logs(conv)[-1].startswith("call:ended:audio:")


def test_room_finished_ends_a_live_call_once(client, client_for):
    _a, _b, _conv, call = _answered_dm(client_for)
    _webhook(client, _wh_event("room_finished", call.room))
    _webhook(client, _wh_event("room_finished", call.room))
    call.refresh_from_db()
    assert call.state == "ended"
    assert len(_events("call.ended")) == 1


def test_someone_who_may_not_be_there_is_kicked_on_join(
    client, client_for, lk, django_capture_on_commit_callbacks
):
    owner, (x, y), conv = _group()
    call_id = _start(client_for(owner), conv).json()["data"]["call_id"]
    room = Call.objects.get(id=call_id).room
    stranger = _acct()
    with django_capture_on_commit_callbacks(execute=True):
        r = _webhook(client, _wh_event("participant_joined", room, stranger))
    assert r.json()["data"]["outcome"] == "kicked"
    # y never accepted (still ringing): a token from elsewhere is not a seat.
    with django_capture_on_commit_callbacks(execute=True):
        _webhook(client, _wh_event("participant_joined", room, y))
    assert lk.removed == [(room, stranger), (room, y)]


def test_a_webhook_for_an_unknown_room_or_event_changes_nothing(client, client_for):
    a, _b, _conv, call = _answered_dm(client_for)
    r = _webhook(client, _wh_event("participant_joined", "call_unknown", a))
    assert r.json()["data"]["outcome"] == "unknown_room"
    r = _webhook(client, _wh_event("track_published", call.room, a))
    assert r.json()["data"]["outcome"] == "ignored"


def test_the_webhook_is_off_with_calls(client, settings):
    settings.LIVEKIT_API_SECRET = ""
    r = client.post(
        reverse("calls_internal:livekit-webhook"), data="{}", content_type="application/json"
    )
    assert r.status_code == 503


# ---- reconcile -----------------------------------------------------------------------------


def test_reconcile_ends_a_quiet_call_whose_room_is_empty(client_for, lk):
    _a, _b, _conv, call = _answered_dm(client_for)
    Call.objects.filter(id=call.id).update(updated_at=timezone.now() - timedelta(minutes=5))
    lk.down = True
    assert calls.reconcile_live() == 0  # LiveKit unreachable: leave it alone
    lk.down = False
    lk.rooms[call.room] = [str(_a)]
    assert calls.reconcile_live() == 0  # still talking
    Call.objects.filter(id=call.id).update(updated_at=timezone.now() - timedelta(minutes=5))
    lk.rooms.pop(call.room)
    assert calls.reconcile_live() == 1
    call.refresh_from_db()
    assert call.state == "ended" and call.end_reason == "lost"


# ---- event contracts ----------------------------------------------------------------------

SCHEMAS = "/opt/tara/libs/tara_events/tara_events/schemas"


def _check(payload: dict, schema: dict) -> None:
    assert set(payload) == set(schema["required"]), schema["title"]
    for key, rule in schema["properties"].items():
        if "enum" in rule:
            assert payload[key] in rule["enum"], (schema["title"], key)
        if rule.get("type") == "array":
            assert isinstance(payload[key], list)


def test_emitted_payloads_match_their_json_schemas(client_for, django_capture_on_commit_callbacks):
    import os

    if not os.path.isdir(SCHEMAS):
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    owner, (x, y), conv = _group()
    call_id = _start(client_for(owner), conv).json()["data"]["call_id"]
    client_for(x).post(reverse("calls:join", args=[call_id]))
    client_for(y).post(reverse("calls:decline", args=[call_id]))
    with django_capture_on_commit_callbacks(execute=True):
        chat.remove_member(owner, str(conv.id), x)  # revoked seat
    a, b, dm = _dm()
    missed = _start(client_for(a), dm).json()["data"]["call_id"]
    client_for(a).post(reverse("calls:end", args=[missed]))
    seen = set()
    for row in OutboxEvent.objects.filter(event_type__startswith="call."):
        with open(f"{SCHEMAS}/{row.event_type}.v1.json", encoding="utf-8") as f:
            _check(row.payload["payload"], json.load(f))
        seen.add(row.event_type)
    assert seen == {"call.started", "call.answered", "call.declined", "call.ended", "call.missed"}
