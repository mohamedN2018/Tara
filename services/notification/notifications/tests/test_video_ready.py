"""Video pipeline (5.2): ``media.processed`` for a transcoded video tells its owner once."""

import uuid

import pytest

from notifications import handlers, registry, video_handlers
from notifications.models import Notification, ProcessedEvent
from tara_events.envelope import EventEnvelope
from tara_events.worker import EventWorker

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _processed(media_id, owner, **payload):
    return EventEnvelope(
        event_type="media.processed",
        subject_id=media_id,
        producer="media-service",
        payload={"owner": owner, "kind": "video", "purpose": "post", **payload},
        actor_id=owner,
    )


def test_the_owner_is_told_the_video_is_ready():
    media_id, owner = _acct(), _acct()
    video_handlers.on_media_processed(_processed(media_id, owner, renditions=[240, 360]))
    (row,) = Notification.objects.filter(kind="video.ready")
    assert str(row.recipient_id) == owner
    assert row.actor_id is None
    assert row.subject_ref == f"media:{media_id}"
    assert registry.category_of("video.ready") == "social"
    assert registry.url_for(row) == "/notifications"


@pytest.mark.parametrize(
    "payload", [{"kind": "image", "purpose": ""}, {"kind": "video", "purpose": ""}]
)
def test_photos_and_chat_videos_are_not_news(payload):
    video_handlers.on_media_processed(_processed(_acct(), _acct(), **payload))
    assert not Notification.objects.filter(kind="video.ready").exists()


def test_replaying_media_processed_notifies_once():
    media_id, owner = _acct(), _acct()
    envelope = _processed(media_id, owner)
    worker = EventWorker.__new__(EventWorker)
    worker.processed_model = ProcessedEvent
    worker.consumer_name = "notification"
    worker._dispatch(envelope)
    worker._dispatch(envelope)  # broker redelivery: the guard drops it
    video_handlers.on_media_processed(_processed(media_id, owner))  # a new envelope, same video
    assert Notification.objects.filter(kind="video.ready").count() == 1


def test_the_handler_is_registered_with_the_consumer():
    from tara_events.dispatch import handlers_for

    assert handlers
    assert any(h is video_handlers.on_media_processed for h in handlers_for("media.processed"))
