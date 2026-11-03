# Roadmap 1.11: the group feed index, built CONCURRENTLY (the post table is large),
# so this migration runs outside a transaction (roadmap 3.3, "Migrations").

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posts", "0007_group_posts_and_readmodels"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="post",
            index=models.Index(
                condition=models.Q(("group_id__isnull", False)),
                fields=["group_id", "-created_at"],
                name="post_group_idx",
            ),
        ),
    ]
