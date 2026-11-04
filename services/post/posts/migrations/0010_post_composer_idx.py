# Wave 2C: the scheduled-post and drafts indexes, built CONCURRENTLY (the post table
# is large), so this migration runs outside a transaction (roadmap 3.3, "Migrations").

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posts", "0009_composer_tags_drafts_schedule"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="post",
            index=models.Index(
                condition=models.Q(("state", "scheduled")),
                fields=["publish_at"],
                name="post_scheduled_idx",
            ),
        ),
        AddIndexConcurrently(
            model_name="post",
            index=models.Index(
                condition=models.Q(("state", "published"), _negated=True),
                fields=["author_id", "-updated_at"],
                name="post_drafts_idx",
            ),
        ),
    ]
