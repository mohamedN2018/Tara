# The settings activity log: an account's own comments and reactions, newest
# first. Built CONCURRENTLY (both tables are large), so this migration runs
# outside a transaction (roadmap 3.3, "Migrations").

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posts", "0011_post_type_reel"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="comment",
            index=models.Index(fields=["author_id", "-created_at"], name="comment_author_idx"),
        ),
        AddIndexConcurrently(
            model_name="postreaction",
            index=models.Index(fields=["account_id", "-created_at"], name="post_reaction_acct_idx"),
        ),
    ]
