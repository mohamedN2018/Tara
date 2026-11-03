# Roadmap 4.4: pg_trgm (a trusted extension, so the database owner can create it)
# and the browse/sort indexes, built CONCURRENTLY so writes are never blocked.

import django.contrib.postgres.indexes
from django.contrib.postgres.operations import AddIndexConcurrently, TrigramExtension
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("marketplace", "0006_validate_listing_checks"),
    ]

    operations = [
        TrigramExtension(),
        AddIndexConcurrently(
            model_name="listing",
            index=models.Index(fields=["status", "created_at", "id"], name="listing_newest_idx"),
        ),
        AddIndexConcurrently(
            model_name="listing",
            index=models.Index(
                fields=["status", "effective_price", "id"], name="listing_price_idx"
            ),
        ),
        AddIndexConcurrently(
            model_name="listing",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["search_text"], name="listing_search_trgm", opclasses=["gin_trgm_ops"]
            ),
        ),
        AddIndexConcurrently(
            model_name="listingsave",
            index=models.Index(fields=["account_id", "-created_at"], name="listing_save_recent_idx"),
        ),
    ]
