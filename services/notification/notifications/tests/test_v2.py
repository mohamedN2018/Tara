"""Notification v2: kind registry, deep links, aggregation, live list API, cleanup."""

import json
import threading
import uuid
from datetime import timedelta
from unittest import mock

import pytest
from django.db import connection, transaction
from django.urls import reverse
from django.utils import timezone

from notifications import handlers, push, registry, services
from notifications.models import (
    Notification,
    NotificationActor,
    NotificationPreference,
    OutboxEvent,
)
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _event(event_type, payload, *, subject_id=None, actor_id=None, producer="test"):
    return EventEnvelope(
        event_type=event_type,
        subject_id=subject_id or str(uuid.uuid4()),
        producer=producer,
        payload=payload,
        actor_id=actor_id,
    )


def _react(author, reactor, post_id):
    handlers.on_post_reacted(
        _event(
            "post.reacted",
            {"post_id": post_id, "author_id": author, "reactor": reactor, "reaction_type": "like"},
            subject_id=post_id,
        )
    )


# ---- registry and deep links ---------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "kwargs", "url"),
    [
        ("post.reaction", {"subject_ref": "post:p1"}, "/posts/p1"),
        (
            "post.comment",
            {"subject_ref": "post:p1", "target_ref": "comment:c1"},
            "/posts/p1?comment=c1",
        ),
        (
            "comment.reply",
            {"subject_ref": "post:p1", "target_ref": "comment:c2"},
            "/posts/p1?comment=c2",
        ),
        ("mention", {"subject_ref": "post:p1"}, "/posts/p1"),
        (
            "post.share",
            {"subject_ref": "post:p1", "actor_count": 1, "data": {"share_post_id": "s1"}},
            "/posts/s1",
        ),
        (
            "post.share",
            {"subject_ref": "post:p1", "actor_count": 3, "data": {"share_post_id": "s1"}},
            "/posts/p1",
        ),
        ("friend.request", {"subject_ref": "account:a1"}, "/u/id/a1"),
        ("friend.request", {"actor_id": "a2"}, "/u/id/a2"),  # rows from before target refs
        ("follow", {"subject_ref": "account:a1", "actor_count": 1}, "/u/id/a1"),
        ("follow", {"subject_ref": "account:a1", "actor_count": 4}, "/connections?tab=followers"),
        ("message", {"subject_ref": "conversation:k1"}, "/messages/k1"),
        ("listing.status", {"subject_ref": "listing:l1"}, "/marketplace/l1"),
        ("page.follow", {"subject_ref": "page:g1", "data": {"page_handle": "cafe"}}, "/pages/cafe"),
        ("page.follow", {"subject_ref": "page:g1"}, "/pages/g1"),
        ("ad.review", {"subject_ref": "campaign:c9"}, "/ads/campaigns/c9"),
        ("unknown.kind", {}, "/notifications"),
        ("post.reaction", {"subject_ref": "post:a/../b?x"}, "/posts/a%2F..%2Fb%3Fx"),
    ],
)
def test_every_kind_links_to_its_target(kind, kwargs, url):
    assert registry.build_url(kind, **kwargs) == url


def test_data_is_whitelisted_and_bounded():
    data = registry.clean_data(
        {"post_id": "p", "email": "x@example.com", "comment_id": None, "status": "x" * 500}
    )
    assert data == {"post_id": "p", "status": "x" * registry.MAX_DATA_VALUE}
    assert len(json.dumps(registry.clean_data(dict.fromkeys(registry.DATA_KEYS, "y" * 120)))) <= (
        registry.MAX_DATA_BYTES
    )


def test_preference_lookup_is_kind_then_category_then_default():
    prefs = {"social": {"push": False}, "post.reaction": {"push": True}}
    assert registry.channel_enabled(prefs, "post.reaction", "push") is True
    assert registry.channel_enabled(prefs, "post.comment", "push") is False
    assert registry.channel_enabled(prefs, "follow", "push") is True
    assert registry.channel_enabled({"follow": True}, "follow", "in_app") is True  # old flat shape


def test_comment_notification_carries_its_deep_link(client_for):
    author, commenter = _acct(), _acct()
    post_id, comment_id = str(uuid.uuid4()), str(uuid.uuid4())
    handlers.on_post_commented(
        _event(
            "post.commented",
            {
                "post_id": post_id,
                "comment_id": comment_id,
                "author": commenter,
                "post_author_id": author,
            },
        )
    )
    row = client_for(author).get(reverse("notifications:list")).json()["data"][0]
    assert row["url"] == f"/posts/{post_id}?comment={comment_id}"
    assert row["category"] == "social"
    assert row["data"] == {"post_id": post_id, "comment_id": comment_id}


# ---- aggregation ------------------------------------------------------------------------


def test_25_reactions_make_one_unread_row_counting_people():
    author, post_id = _acct(), str(uuid.uuid4())
    reactors = [_acct() for _ in range(25)]
    for reactor in reactors:
        _react(author, reactor, post_id)
    _react(author, reactors[0], post_id)  # the same person again is not a new actor

    row = Notification.objects.get(recipient_id=author)
    assert row.actor_count == 25
    assert row.read_at is None
    assert row.recent_actor_ids == [reactors[0], reactors[24], reactors[23]]
    assert NotificationActor.objects.filter(notification=row).count() == 25


def test_other_posts_and_other_recipients_do_not_merge():
    author, other = _acct(), _acct()
    reactor = _acct()
    _react(author, reactor, "p1")
    _react(author, reactor, "p2")
    _react(other, reactor, "p1")
    assert Notification.objects.count() == 3


def test_expired_aggregate_is_closed_and_a_new_row_starts():
    author, post_id = _acct(), str(uuid.uuid4())
    _react(author, _acct(), post_id)
    old = Notification.objects.get(recipient_id=author)
    Notification.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(hours=25))

    _react(author, _acct(), post_id)  # no IntegrityError

    old.refresh_from_db()
    assert old.aggregate_key == registry.closed_key(f"post.reaction|post:{post_id}", old.id)
    assert old.actor_count == 1
    fresh = Notification.objects.exclude(id=old.id).get(recipient_id=author)
    assert fresh.aggregate_key == f"post.reaction|post:{post_id}"
    assert fresh.actor_count == 1


def test_reading_an_aggregate_closes_it():
    author, post_id = _acct(), str(uuid.uuid4())
    _react(author, _acct(), post_id)
    services.mark_read(author, mark_all=True)
    _react(author, _acct(), post_id)
    assert Notification.objects.filter(recipient_id=author).count() == 2
    assert services.unread_count(author) == 1


def test_merge_announces_again_and_pushes_only_the_first_event(
    django_capture_on_commit_callbacks,
):
    author, post_id = _acct(), str(uuid.uuid4())
    with (
        mock.patch("notifications.services._queue_push") as queue,
        django_capture_on_commit_callbacks(execute=True),
    ):
        _react(author, _acct(), post_id)
        _react(author, _acct(), post_id)
    assert queue.call_count == 1
    created = OutboxEvent.objects.filter(event_type="notification.created")
    assert created.count() == 2
    assert all(
        set(e.payload["payload"]) == {"recipient", "kind", "notification_id", "actor"}
        for e in created
    )


def test_message_rows_group_per_conversation_and_push_every_message(
    django_capture_on_commit_callbacks,
):
    sender, reader, conversation = _acct(), _acct(), str(uuid.uuid4())
    payload = {
        "conversation_id": conversation,
        "sender": sender,
        "recipients": [sender, reader],
        "muted": [],
        "type": "image",
        "preview": "",
    }
    with (
        mock.patch("notifications.services._queue_push") as queue,
        django_capture_on_commit_callbacks(execute=True),
    ):
        handlers.on_message_created(_event("message.created", payload))
        handlers.on_message_created(_event("message.created", {**payload, "preview": "hi"}))
    row = Notification.objects.get(recipient_id=reader)
    assert row.body == "hi"
    assert queue.call_count == 2

    handlers.on_message_read(
        _event("message.read", {"conversation_id": conversation, "reader": reader})
    )
    assert services.unread_count(reader) == 0
    assert OutboxEvent.objects.filter(event_type="notification.read").exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_first_events_merge_into_one_row():
    """Both consumers find no open row; the unique index lets one insert, the
    other retries and merges instead of dead-lettering."""
    author, post_id = _acct(), str(uuid.uuid4())
    first_inserted = threading.Event()
    errors: list[BaseException] = []

    def slow_first():
        try:
            with transaction.atomic():
                _react(author, _acct(), post_id)
                first_inserted.set()
                threading.Event().wait(0.5)  # hold the uncommitted insert
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    def second():
        try:
            first_inserted.wait(5)
            _react(author, _acct(), post_id)  # blocks on the index, then merges
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=slow_first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert errors == []
    row = Notification.objects.get(recipient_id=author)
    assert row.actor_count == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("expired", [False, True])
def test_burst_of_concurrent_events_keeps_one_open_row(expired):
    author, post_id = _acct(), str(uuid.uuid4())
    if expired:
        _react(author, _acct(), post_id)
        Notification.objects.update(created_at=timezone.now() - timedelta(days=2))
    workers = 8
    barrier = threading.Barrier(workers)
    errors: list[BaseException] = []

    def work():
        try:
            barrier.wait(5)
            _react(author, _acct(), post_id)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=work) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert errors == []
    open_rows = Notification.objects.filter(recipient_id=author, read_at__isnull=True).exclude(
        aggregate_key__contains="~"
    )
    assert open_rows.count() == 1
    assert open_rows.get().actor_count == workers


# ---- channels ---------------------------------------------------------------------------


def test_push_only_kind_keeps_a_hidden_read_row(django_capture_on_commit_callbacks, client_for):
    me = _acct()
    NotificationPreference.objects.create(account_id=me, prefs={"follow": {"in_app": False}})
    with (
        mock.patch("notifications.services._queue_push") as queue,
        django_capture_on_commit_callbacks(execute=True),
    ):
        row = services.notify(me, "follow", actor_id=_acct())
    assert row.visible_in_app is False and row.read_at is not None and row.aggregate_key == ""
    queue.assert_called_once()
    client = client_for(me)
    assert client.get(reverse("notifications:list")).json()["data"] == []
    assert client.get(reverse("notifications:unread-count")).json()["data"]["unread"] == 0


def test_category_mute_applies_to_every_kind_in_it():
    me = _acct()
    NotificationPreference.objects.create(
        account_id=me, prefs={"social": {"in_app": False, "push": False}}
    )
    assert services.notify(me, "post.comment", actor_id=_acct()) is None
    assert services.notify(me, "follow", actor_id=_acct()) is not None


def test_preferences_merge_and_validate(client_for):
    client = client_for(_acct())
    url = reverse("notifications:preferences")
    client.patch(url, {"prefs": {"follow": {"in_app": False}}}, format="json")
    resp = client.patch(url, {"prefs": {"post.reaction": {"push": False}}}, format="json")
    assert resp.json()["data"]["prefs"] == {
        "follow": {"in_app": False},
        "post.reaction": {"push": False},
    }
    resp = client.patch(url, {"prefs": {"follow": {"in_app": None}}}, format="json")
    assert resp.json()["data"]["prefs"] == {"post.reaction": {"push": False}}
    resp = client.patch(url, {"message_previews": False}, format="json")
    assert resp.json()["data"]["message_previews"] is False
    assert resp.json()["data"]["prefs"] == {"post.reaction": {"push": False}}

    assert client.patch(url, {"prefs": {"nope": {"push": False}}}, format="json").status_code == 400
    assert (
        client.patch(url, {"prefs": {"follow": {"email": False}}}, format="json").status_code == 400
    )


def test_kinds_endpoint_describes_the_registry(client_for):
    data = client_for(_acct()).get(reverse("notifications:kinds")).json()["data"]
    assert data["categories"] == list(registry.CATEGORIES)
    kinds = {k["kind"]: k for k in data["kinds"]}
    assert kinds["friend.request"]["resolutions"] == ["accepted", "declined", "expired"]
    assert kinds["post.reaction"]["aggregates"] is True


# ---- live list API ----------------------------------------------------------------------


def test_fetch_one_by_id_only_for_its_owner(client_for):
    me = _acct()
    row = services.notify(me, "mention", actor_id=_acct(), subject_ref="post:p")
    url = reverse("notifications:detail", args=[row.id])
    assert client_for(me).get(url).json()["data"]["id"] == str(row.id)
    assert client_for(_acct()).get(url).status_code == 404


def test_dismiss_deletes_and_announces(client_for):
    me = _acct()
    row = services.notify(me, "mention", actor_id=_acct(), subject_ref="post:p")
    url = reverse("notifications:detail", args=[row.id])
    assert client_for(_acct()).delete(url).status_code == 204
    assert Notification.objects.filter(id=row.id).exists()  # not yours: untouched
    assert client_for(me).delete(url).status_code == 204
    assert not Notification.objects.filter(id=row.id).exists()
    event = OutboxEvent.objects.get(event_type="notification.deleted")
    assert event.payload["payload"]["notification_ids"] == [str(row.id)]


def test_read_ids_are_capped_and_reads_are_announced(client_for):
    me = _acct()
    client = client_for(me)
    url = reverse("notifications:read")
    too_many = {"ids": [str(uuid.uuid4()) for _ in range(101)]}
    assert client.post(url, too_many, format="json").status_code == 400

    row = services.notify(me, "mention", actor_id=_acct(), subject_ref="post:p")
    assert client.post(url, {"ids": [str(row.id)]}, format="json").json()["data"] == {
        "marked_read": 1
    }
    event = OutboxEvent.objects.get(event_type="notification.read")
    assert event.payload["payload"] == {
        "recipient": me,
        "notification_ids": [str(row.id)],
        "all": False,
    }


def test_list_filters_by_category(client_for):
    me = _acct()
    services.notify(me, "mention", actor_id=_acct(), subject_ref="post:p")
    services.notify(me, "friend.accepted", actor_id=_acct())
    client = client_for(me)
    rows = client.get(reverse("notifications:list"), {"category": "connections"}).json()["data"]
    assert [r["kind"] for r in rows] == ["friend.accepted"]
    assert client.get(reverse("notifications:list"), {"category": "x"}).status_code == 400


def test_aggregate_moves_to_the_top_of_the_list(client_for):
    me, post_id = _acct(), str(uuid.uuid4())
    _react(me, _acct(), post_id)
    services.notify(me, "mention", actor_id=_acct(), subject_ref="post:other")
    _react(me, _acct(), post_id)
    rows = client_for(me).get(reverse("notifications:list")).json()["data"]
    assert [r["kind"] for r in rows] == ["post.reaction", "mention"]
    assert rows[0]["actor_count"] == 2


# ---- inline actions ---------------------------------------------------------------------


def _friend_request(me):
    request_id = str(uuid.uuid4())
    handlers.on_friend_requested(
        _event("friendship.requested", {"from": _acct(), "to": me}, subject_id=request_id)
    )
    return request_id, Notification.objects.get(recipient_id=me, kind="friend.request")


def test_client_records_a_resolution_the_kind_allows(client_for):
    me = _acct()
    _, row = _friend_request(me)
    url = reverse("notifications:resolve", args=[row.id])
    client = client_for(me)
    resp = client.post(url, {"resolution": "declined"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["resolution"] == "declined"
    assert resp.json()["data"]["read_at"] is not None
    assert client.post(url, {"resolution": "followed_back"}, format="json").status_code == 400
    assert client_for(_acct()).post(url, {"resolution": "declined"}, format="json").status_code == (
        404
    )


def test_accepting_anywhere_resolves_the_request_notification():
    me = _acct()
    request_id, row = _friend_request(me)
    handlers.on_friend_accepted(
        _event("friendship.accepted", {"a": me, "b": _acct()}, subject_id=request_id, actor_id=me)
    )
    row.refresh_from_db()
    assert row.resolution == "accepted" and row.read_at is not None


def test_withdrawn_request_is_resolved():
    me = _acct()
    request_id, row = _friend_request(me)
    handlers.on_friend_request_withdrawn(
        _event("friendship.request.withdrawn", {}, subject_id=request_id)
    )
    row.refresh_from_db()
    assert row.resolution == "withdrawn"


# ---- cleanup ----------------------------------------------------------------------------


def test_deleted_post_takes_its_notifications(client_for):
    author, post_id = _acct(), str(uuid.uuid4())
    _react(author, _acct(), post_id)
    handlers.on_post_deleted(_event("post.deleted", {"post_id": post_id}, subject_id=post_id))
    assert not Notification.objects.filter(recipient_id=author).exists()


def test_block_removes_one_actor_and_keeps_the_others():
    author, blocked, friend, post_id = _acct(), _acct(), _acct(), str(uuid.uuid4())
    _react(author, friend, post_id)
    _react(author, blocked, post_id)
    services.notify(author, "mention", actor_id=blocked, subject_ref="post:x")

    handlers.on_user_blocked(_event("user.blocked", {"blocker_id": author, "blocked_id": blocked}))

    row = Notification.objects.get(recipient_id=author)
    assert row.kind == "post.reaction"
    assert row.actor_count == 1
    assert row.recent_actor_ids == [friend]
    assert str(row.actor_id) == friend


def test_seller_is_not_told_about_their_own_listing_change():
    seller, moderator = _acct(), _acct()
    payload = {"listing_id": "l1", "seller_id": seller, "to": "sold"}
    handlers.on_listing_status(_event("listing.status.changed", payload, actor_id=seller))
    assert not Notification.objects.exists()
    handlers.on_listing_status(_event("listing.status.changed", payload, actor_id=moderator))
    row = Notification.objects.get(recipient_id=seller)
    assert row.actor_id is None  # moderators are not named
    assert row.data == {"listing_id": "l1", "status": "sold"}


# ---- push payload -----------------------------------------------------------------------


def test_push_payload_has_the_deep_link_count_and_honours_previews():
    me = _acct()
    row = services.notify(
        me,
        "post.comment",
        actor_id=_acct(),
        subject_ref="post:p1",
        target_ref="comment:c1",
    )
    payload = json.loads(push._payload(row))
    assert payload["url"] == "/posts/p1?comment=c1"
    assert payload["count"] == 1
    assert payload["tag"] == "post.comment|post:p1"

    pref = NotificationPreference.objects.create(account_id=me, message_previews=False)
    message = services.notify(
        me, "message", actor_id=_acct(), subject_ref="conversation:k", body="secret"
    )
    assert json.loads(push._payload(message, pref))["body"] == ""
    assert json.loads(push._payload(message))["body"] == "secret"
