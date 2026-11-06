"""WP 4c.8-B3 (08 section 7.3): the keyset index of the chronological modes.

``(recipient_id, post_created_at DESC, id DESC)`` serves ``key < t OR (key = t AND
id < i)`` per recipient. It replaces ``feed_recipient_idx`` (the same columns
without ``id``). Both steps run ``CONCURRENTLY`` outside a transaction, so the feed
table is never locked against writes while the index builds; the old index is
dropped only after the new one is valid. Additive: the reverse rebuilds the old
index first, then drops the new one, the same way.
"""

from django.contrib.postgres.operations import AddIndexConcurrently, RemoveIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("feed", "0011_author_age_class")]

    operations = [
        AddIndexConcurrently(
            model_name="feeditem",
            index=models.Index(
                fields=["recipient_id", "-post_created_at", "-id"], name="feed_recipient_ts_idx"
            ),
        ),
        RemoveIndexConcurrently(model_name="feeditem", name="feed_recipient_idx"),
    ]
