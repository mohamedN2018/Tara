"""Index post_media.media_id ("is this media already on a post?").

post_media grows with every photo post, so the index is built CONCURRENTLY,
outside a transaction, and does not block writes (roadmap 3.3, Migrations).
"""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posts", "0003_post_report_unique"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="postmedia",
            index=models.Index(fields=["media_id"], name="post_media_media_idx"),
        ),
    ]
