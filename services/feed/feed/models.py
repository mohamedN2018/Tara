"""Feed domain models (owns `feed_db`). All rows are DERIVED and rebuildable.

Each FeedItem carries a denormalized post snapshot so the feed read path never
needs a synchronous call to the Post service — the feed stays readable even if
Post is down (graceful degradation, doc 02 §5). Only public posts and the
author's own item keep content (excerpt, media ids) in the snapshot; every other
item holds ids and enums, and the client hydrates it through `/posts/batch/`,
which re-checks visibility (`services.snapshot_for`).
"""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent


class FeedItem(models.Model):
    class Reason(models.TextChoices):
        """Why the item reached the recipient. Unfollow removes only FOLLOW items."""

        SELF = "self", "Own post"
        FRIEND = "friend", "Friend of the author"
        FOLLOW = "follow", "Follows the author"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    recipient_id = models.UUIDField()
    post_id = models.UUIDField()
    author_id = models.UUIDField()
    score = models.FloatField(default=0.0)  # ranking signal (chronological default)
    reason = models.CharField(max_length=40, choices=Reason.choices, default=Reason.FOLLOW)
    snapshot = models.JSONField(default=dict)  # denormalized post data for rendering
    post_created_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feed_item"
        constraints = [
            models.UniqueConstraint(fields=["recipient_id", "post_id"], name="feed_item_uniq"),
        ]
        indexes = [
            models.Index(fields=["recipient_id", "-post_created_at"], name="feed_recipient_idx"),
        ]


class OutboxEvent(AbstractOutboxEvent):
    class Meta(AbstractOutboxEvent.Meta):
        abstract = False
        db_table = "outbox_event"


class ProcessedEvent(AbstractProcessedEvent):
    class Meta(AbstractProcessedEvent.Meta):
        abstract = False
        db_table = "processed_event"
