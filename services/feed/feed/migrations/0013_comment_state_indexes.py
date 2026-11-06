"""R3 verifier: indexes for the reads of ``comment_state`` on the first page.

Until now the table had only its primary key, so three first-page reads scanned it:
the per-post distinct-commenter feature (``intel/ranking/features.py``, by
``post_id``), the conversation relationship read (by ``author_id`` /
``post_author_id`` since a time) and the conversation exception of the exposure
multiplier (``intel/ranking/exposure_rank.py::new_commenters``: by ``post_id`` after
the viewer's last display, and one commenter's burst window by ``author_id``).
Built ``CONCURRENTLY`` outside a transaction (as ``0012``), so comment events are
never blocked while an index builds. Additive: the reverse drops them the same way.
"""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("feed", "0012_feed_recipient_keyset_idx")]

    operations = [
        AddIndexConcurrently(
            model_name="commentstate",
            index=models.Index(fields=["post_id", "occurred_at"], name="comment_state_post_idx"),
        ),
        AddIndexConcurrently(
            model_name="commentstate",
            index=models.Index(
                fields=["author_id", "occurred_at"], name="comment_state_author_idx"
            ),
        ),
        AddIndexConcurrently(
            model_name="commentstate",
            index=models.Index(
                fields=["post_author_id", "occurred_at"], name="comment_state_post_author_idx"
            ),
        ),
    ]
