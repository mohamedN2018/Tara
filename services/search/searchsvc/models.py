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
    doc_id = models.CharField(max_length=64)
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


class ProcessedEvent(AbstractProcessedEvent):
    class Meta(AbstractProcessedEvent.Meta):
        abstract = False
        db_table = "processed_event"
