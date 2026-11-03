"""Notification consumers + API tests."""

import uuid

import pytest
from django.urls import reverse

from notifications.handlers import (
    on_comment_replied,
    on_message_created,
    on_post_reacted,
    on_post_shared,
    on_user_followed,
    on_user_mentioned,
)
from notifications.models import Notification, NotificationPreference, OutboxEvent
from notifications.services import notify
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def test_post_reacted_creates_notification_and_emits():
    author, reactor = _acct(), _acct()
    on_post_reacted(
        EventEnvelope(
            event_type="post.reacted",
            subject_id="p1",
            producer="post-service",
            payload={
                "post_id": "p1",
                "author_id": author,
                "reactor": reactor,
                "reaction_type": "like",
            },
        )
    )
    assert Notification.objects.filter(recipient_id=author, kind="post.reaction").count() == 1
    assert OutboxEvent.objects.filter(event_type="notification.created").exists()


def test_no_self_notification():
    me = _acct()
    on_user_followed(
        EventEnvelope(
            event_type="user.followed",
            subject_id="f1",
            producer="graph-service",
            payload={"follower": me, "target": me, "target_type": "user"},
        )
    )
    assert Notification.objects.count() == 0


def test_list_unread_and_mark_read(client_for):
    me = _acct()
    notify(me, "post.reaction", actor_id=_acct(), body="x")
    notify(me, "follow", actor_id=_acct(), body="y")
    client = client_for(me)

    listing = client.get(reverse("notifications:list"), {"unread": "1"})
    assert listing.status_code == 200
    assert len(listing.json()["data"]) == 2

    assert client.get(reverse("notifications:unread-count")).json()["data"]["unread"] == 2

    marked = client.post(reverse("notifications:read"), {"all": True}, format="json")
    assert marked.json()["data"]["marked_read"] == 2
    assert client.get(reverse("notifications:unread-count")).json()["data"]["unread"] == 0


def test_only_own_notifications_visible(client_for):
    me, other = _acct(), _acct()
    notify(other, "follow", actor_id=_acct(), body="not yours")
    listing = client_for(me).get(reverse("notifications:list"))
    assert listing.json()["data"] == []


def test_push_token_registration(client_for):
    me = _acct()
    resp = client_for(me).post(
        reverse("notifications:push-token"),
        {"platform": "ios", "token": "device-token-123"},
        format="json",
    )
    assert resp.status_code == 201


def test_preferences_mute_suppresses_notification(client_for):
    me = _acct()
    client = client_for(me)
    # Mute the "follow" kind for in-app.
    client.patch(
        reverse("notifications:preferences"),
        {"prefs": {"follow": {"in_app": False}}},
        format="json",
    )
    notify(me, "follow", actor_id=_acct(), body="should be suppressed")
    assert Notification.objects.filter(recipient_id=me, kind="follow").count() == 0


def test_flat_preferences_are_rejected_and_nested_ones_mute(client_for):
    user = _acct()
    client = client_for(user)
    url = reverse("notifications:preferences")

    assert client.patch(url, {"prefs": {"follow": True}}, format="json").status_code == 400

    body = {"prefs": {"follow": {"in_app": False}}}
    assert client.patch(url, body, format="json").status_code == 200
    assert notify(user, "follow", actor_id=_acct()) is None


def test_old_flat_preferences_do_not_break_delivery():
    user = _acct()
    NotificationPreference.objects.create(account_id=user, prefs={"follow": True})
    assert notify(user, "follow", actor_id=_acct()) is not None


def test_comment_reply_notifies_the_parent_comment_author():
    post_author, parent_author, replier = _acct(), _acct(), _acct()
    on_comment_replied(
        EventEnvelope(
            event_type="comment.replied",
            subject_id=str(uuid.uuid4()),
            producer="post-service",
            payload={
                "post_id": str(uuid.uuid4()),
                "author": replier,
                "post_author_id": post_author,
                "parent_author_id": parent_author,
            },
        )
    )
    assert Notification.objects.filter(recipient_id=parent_author, kind="comment.reply").exists()
    assert not Notification.objects.filter(recipient_id=post_author).exists()


@pytest.mark.parametrize(
    "value",
    [
        "22:00",
        {"start": "22:00"},
        {"start": "25:00", "end": "07:00"},
        {"start": "7:00", "end": "22:00"},
        {"start": "22:00", "end": "22:00"},
        {"start": "22:00", "end": "07:00", "timezone": "Mars/Base"},
        {"start": "22:00", "end": "07:00", "extra": 1},
    ],
)
def test_bad_quiet_hours_are_rejected_with_field_details(client_for, value):
    resp = client_for(_acct()).patch(
        reverse("notifications:preferences"), {"quiet_hours": value}, format="json"
    )
    assert resp.status_code == 400
    error = resp.json()["error"]
    assert error["code"] == "validation_error"
    assert [d["field"] for d in error["details"]] == ["quiet_hours"]


def test_quiet_hours_are_stored_and_can_be_cleared(client_for):
    client = client_for(_acct())
    url = reverse("notifications:preferences")
    resp = client.patch(
        url,
        {"quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "Africa/Cairo"}},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["quiet_hours"]["timezone"] == "Africa/Cairo"
    resp = client.patch(url, {"quiet_hours": {}}, format="json")
    assert resp.json()["data"]["quiet_hours"] == {}


def test_muted_member_gets_no_message_notification():
    sender, muted, listening = _acct(), _acct(), _acct()
    on_message_created(
        EventEnvelope(
            event_type="message.created",
            subject_id=str(uuid.uuid4()),
            producer="chat-service",
            payload={
                "conversation_id": str(uuid.uuid4()),
                "sender": sender,
                "recipients": [sender, muted, listening],
                "muted": [muted],
                "preview": "hi",
            },
        )
    )
    assert not Notification.objects.filter(recipient_id=muted).exists()
    assert Notification.objects.filter(recipient_id=listening, kind="message").exists()


def test_mention_and_share_notify():
    actor, target = _acct(), _acct()
    post_id = str(uuid.uuid4())
    on_user_mentioned(
        EventEnvelope(
            event_type="user.mentioned",
            subject_id=post_id,
            producer="post-service",
            payload={"recipient": target, "actor": actor, "post_id": post_id},
        )
    )
    on_post_shared(
        EventEnvelope(
            event_type="post.shared",
            subject_id=post_id,
            producer="post-service",
            payload={
                "post_id": post_id,
                "share_post_id": post_id,
                "sharer": actor,
                "author_id": target,
            },
        )
    )
    kinds = set(Notification.objects.filter(recipient_id=target).values_list("kind", flat=True))
    assert kinds == {"mention", "post.share"}
