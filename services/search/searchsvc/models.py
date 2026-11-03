"""Search domain models (owns `search_db`).

`search_document` is the source of truth for the index AND the query fallback
when OpenSearch is unavailable. All rows are derived from domain events.
"""

from __future__ import annotations

from django.db import models

from tara_events.models import AbstractProcessedEvent


class SearchDocument(models.Model):
    DOC_TYPES = ["user", "page", "post", "listing", "hashtag"]

    doc_type = models.CharField(max_length=16)
    # Hashtags are up to 80 characters (post-service `#(\w{1,80})`), so 64 was too short.
    doc_id = models.CharField(max_length=100)
    title = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField(blank=True, default="")
    owner_id = models.UUIDField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "search_document"
        constraints = [
            models.UniqueConstraint(fields=["doc_type", "doc_id"], name="search_doc_uniq"),
        ]
        indexes = [models.Index(fields=["doc_type"], name="search_doctype_idx")]


class PostIndexState(models.Model):
    """The last post event applied per post, kept after a delete (the tombstone).

    Retries reorder events, so an older ``post.created``/``post.updated`` can arrive
    after a newer delete or audience change. It is ignored instead of putting a
    deleted or non-public post (and its hashtags) back into the index.
    """

    post_id = models.CharField(max_length=64, unique=True)
    public = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "post_index_state"


class PublicPostHashtag(models.Model):
    """A hashtag carried by a live PUBLIC post: the only input to hashtag documents.

    A hashtag document exists only while at least one row backs it. Friends,
    followers, only-me, close-friends and group posts never get a row.
    """

    post_id = models.CharField(max_length=64)
    tag = models.CharField(max_length=80)
    author_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "public_post_hashtag"
        constraints = [
            models.UniqueConstraint(fields=["post_id", "tag"], name="search_post_tag_uniq"),
        ]
        indexes = [models.Index(fields=["tag"], name="search_post_tag_idx")]


class BlockedPair(models.Model):
    """Replica of graph blocks, so people who blocked each other never meet in results."""

    blocker_id = models.UUIDField()
    blocked_id = models.UUIDField()

    class Meta:
        db_table = "blocked_pair"
        constraints = [
            models.UniqueConstraint(fields=["blocker_id", "blocked_id"], name="search_block_uniq"),
        ]


class ProcessedEvent(AbstractProcessedEvent):
    class Meta(AbstractProcessedEvent.Meta):
        abstract = False
        db_table = "processed_event"
