"""pg_trgm (a trusted extension, so the database owner can create it) and the
search v2 indexes on existing tables, built CONCURRENTLY so the indexer and the
API are never blocked."""

import django.contrib.postgres.indexes
from django.contrib.postgres.operations import AddIndexConcurrently, TrigramExtension
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("searchsvc", "0006_renormalize_documents"),
    ]

    operations = [
        TrigramExtension(),
        AddIndexConcurrently(
            model_name="searchdocument",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["title_norm"], name="search_title_trgm", opclasses=["gin_trgm_ops"]
            ),
        ),
        AddIndexConcurrently(
            model_name="searchdocument",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["body_norm"], name="search_body_trgm", opclasses=["gin_trgm_ops"]
            ),
        ),
        AddIndexConcurrently(
            model_name="searchdocument",
            index=models.Index(fields=["doc_type", "-source_at", "-id"], name="search_doc_recent_idx"),
        ),
        AddIndexConcurrently(
            model_name="publicposthashtag",
            index=models.Index(fields=["created_at", "tag"], name="search_post_tag_recent_idx"),
        ),
    ]
