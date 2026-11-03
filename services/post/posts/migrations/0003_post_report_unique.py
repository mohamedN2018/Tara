"""One report per account per post.

Existing duplicates (repeat reports from before the dedupe) would make the
constraint fail, so they are dropped first, keeping each reporter's earliest
report. Moderation already has its own copy of every report it received.
post_report is small, so the unique index is built in this transaction.
"""

from django.db import migrations, models


def drop_duplicate_reports(apps, schema_editor):
    PostReport = apps.get_model("posts", "PostReport")
    seen, duplicates = set(), []
    rows = PostReport.objects.order_by("created_at", "id").values_list(
        "id", "post_id", "reporter_id"
    )
    for pk, post_id, reporter_id in rows.iterator(chunk_size=2000):
        if (post_id, reporter_id) in seen:
            duplicates.append(pk)
        else:
            seen.add((post_id, reporter_id))
    for start in range(0, len(duplicates), 1000):
        PostReport.objects.filter(id__in=duplicates[start : start + 1000]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posts", "0002_polls"),
    ]

    operations = [
        migrations.RunPython(drop_duplicate_reports, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="postreport",
            constraint=models.UniqueConstraint(
                fields=("post", "reporter_id"), name="post_report_uniq"
            ),
        ),
    ]
