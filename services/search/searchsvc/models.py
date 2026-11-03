"""Search domain models (owns `search_db`).

`search_document` is the source of truth for the index AND the query fallback
when OpenSearch is unavailable. All rows are derived from domain events.
"""

from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractProcessedEvent


class SearchDocument(models.Model):
    DOC_TYPES = ["user", "page", "post", "listing", "hashtag", "group", "gathering"]

    doc_type = models.CharField(max_length=16)
    # Hashtags are up to 80 characters (post-service `#(\w{1,80})`), so 64 was too short.
    doc_id = models.CharField(max_length=100)
    title = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField(blank=True, default="")
    owner_id = models.UUIDField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Search v2 (1.15): Arabic-normalised copies (`tara_common.text.normalize_ar`)
    # queried with pg_trgm, plus the filter columns. `db_default` so an old
    # indexer still running during a deploy can insert rows.
    title_norm = models.TextField(blank=True, default="", db_default="")
    body_norm = models.TextField(blank=True, default="", db_default="")
    category = models.CharField(max_length=80, blank=True, default="", db_default="")
    location_norm = models.CharField(max_length=160, blank=True, default="", db_default="")
    # The source's own time: a post's creation, an event's start, a listing's
    # creation. Date filters and "most recent" use it (falling back to created_at).
    source_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "search_document"
        constraints = [
            models.UniqueConstraint(fields=["doc_type", "doc_id"], name="search_doc_uniq"),
        ]
        indexes = [
            models.Index(fields=["doc_type"], name="search_doctype_idx"),
            GinIndex(fields=["title_norm"], name="search_title_trgm", opclasses=["gin_trgm_ops"]),
            GinIndex(fields=["body_norm"], name="search_body_trgm", opclasses=["gin_trgm_ops"]),
            models.Index(fields=["doc_type", "-source_at", "-id"], name="search_doc_recent_idx"),
        ]


class DocState(models.Model):
    """The last event applied per document, kept after a removal (the tombstone).

    Retries reorder events, so an older ``page.updated`` or ``group.updated`` can
    arrive after a newer delete, or after a change that took the item out of
    search (a hidden group, a private profile, a sold listing). Each event's
    ``occurred_at`` is compared with ``version_at``: older ones are ignored, so
    they cannot bring the document back. Posts keep their own ``PostIndexState``.
    """

    doc_type = models.CharField(max_length=16)
    doc_id = models.CharField(max_length=100)
    live = models.BooleanField(default=False)
    version_at = models.DateTimeField()

    class Meta:
        db_table = "search_doc_state"
        constraints = [
            models.UniqueConstraint(fields=["doc_type", "doc_id"], name="search_doc_state_uniq"),
        ]


class RecentSearch(models.Model):
    """One account's search history: a typed query or an opened result.

    Private to its owner. Entity rows are shown only while their document is
    still searchable by the owner, so history never revives removed content.
    """

    class Kind(models.TextChoices):
        QUERY = "query", "Query"
        ENTITY = "entity", "Entity"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_id = models.UUIDField()
    kind = models.CharField(max_length=8, choices=Kind.choices)
    query = models.CharField(max_length=200, blank=True, default="")
    query_norm = models.CharField(max_length=200, blank=True, default="")
    doc_type = models.CharField(max_length=16, blank=True, default="")
    doc_id = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField()

    class Meta:
        db_table = "search_recent"
        constraints = [
            models.UniqueConstraint(
                fields=["account_id", "kind", "query_norm", "doc_type", "doc_id"],
                name="search_recent_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["account_id", "-created_at"], name="search_recent_owner_idx"),
        ]


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
        indexes = [
            models.Index(fields=["tag"], name="search_post_tag_idx"),
            # Trending reads the links of a recent window.
            models.Index(fields=["created_at", "tag"], name="search_post_tag_recent_idx"),
        ]


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
