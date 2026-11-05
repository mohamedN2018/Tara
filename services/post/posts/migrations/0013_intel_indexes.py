# Tara Intelligence WP 3.7 (D11): an account's shares newest first, and the
# published, non-group posts of one type newest first (the video listing and
# intelligence's per-type candidate reads). Built CONCURRENTLY (both tables
# are large), so this migration runs outside a transaction, like 0012.

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posts", "0012_activity_log_idx"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="share",
            index=models.Index(fields=["account_id", "-created_at"], name="share_account_idx"),
        ),
        AddIndexConcurrently(
            model_name="post",
            index=models.Index(
                condition=models.Q(("group_id__isnull", True), ("state", "published")),
                fields=["type", "-created_at"],
                name="post_type_published_idx",
            ),
        ),
    ]
