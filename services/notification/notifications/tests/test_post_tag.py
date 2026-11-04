"""Wave 2C: ``post.tagged`` becomes a ``post.tag`` notification for the tagged person."""

import uuid

import pytest

from notifications import handlers, registry, tag_handlers
from notifications.models import Notification
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _tagged(post_id, author, recipient):
    return EventEnvelope(
        event_type="post.tagged",
        subject_id=post_id,
        producer="post-service",
        payload={"post_id": post_id, "author_id": author, "recipient": recipient},
        actor_id=author,
    )


def test_the_tagged_person_is_notified_with_a_link_to_the_post():
    post_id, author, friend = _acct(), _acct(), _acct()
    tag_handlers.on_post_tagged(_tagged(post_id, author, friend))
    (row,) = Notification.objects.filter(kind="post.tag")
    assert str(row.recipient_id) == friend
    assert str(row.actor_id) == author
    assert row.subject_ref == f"post:{post_id}"
    assert row.data == {"post_id": post_id}
    assert registry.url_for(row) == f"/posts/{post_id}"
    assert registry.category_of("post.tag") == "social"


def test_the_handler_is_registered_with_the_consumer():
    from tara_events.dispatch import handlers_for

    assert handlers  # imported for its side effect: tag_handlers registers
    assert any(h is tag_handlers.on_post_tagged for h in handlers_for("post.tagged"))


def test_tagging_yourself_never_notifies():
    me = _acct()
    tag_handlers.on_post_tagged(_tagged(_acct(), me, me))
    assert not Notification.objects.filter(kind="post.tag").exists()


def test_a_deleted_post_takes_its_tag_notification():
    post_id, author, friend = _acct(), _acct(), _acct()
    tag_handlers.on_post_tagged(_tagged(post_id, author, friend))
    handlers.on_post_deleted(
        EventEnvelope(
            event_type="post.deleted",
            subject_id=post_id,
            producer="post-service",
            payload={"post_id": post_id},
        )
    )
    assert not Notification.objects.filter(kind="post.tag").exists()


def test_the_kind_can_be_turned_off_in_settings():
    assert "post.tag" in registry.preference_keys()
    assert any(k["kind"] == "post.tag" for k in registry.describe())
