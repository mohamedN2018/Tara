"""Notification v2 indexes, built CONCURRENTLY so writes are never blocked.

The partial unique index keeps one *open* (unread) aggregate per recipient and
key. Django has no concurrent AddConstraint, so it is created with raw SQL and
recorded in the migration state as the model's UniqueConstraint. Before 0003
no row had an aggregate key, so building it cannot fail on old data.
"""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("notifications", "0004_backfill_notification_v2"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="notification",
            index=models.Index(
                fields=["recipient_id", "-last_event_at", "-id"], name="notif_recipient_recent_idx"
            ),
        ),
        AddIndexConcurrently(
            model_name="notification",
            index=models.Index(
                condition=models.Q(("read_at__isnull", True), ("visible_in_app", True)),
                fields=["recipient_id", "category"],
                name="notif_unread_idx",
            ),
        ),
        AddIndexConcurrently(
            model_name="notification",
            index=models.Index(fields=["subject_ref"], name="notif_subject_idx"),
        ),
        AddIndexConcurrently(
            model_name="notification",
            index=models.Index(fields=["target_ref"], name="notif_target_idx"),
        ),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS notif_open_aggregate_uniq "
                'ON "notification" ("recipient_id", "aggregate_key") '
                "WHERE \"read_at\" IS NULL AND NOT (\"aggregate_key\" = '')"
            ),
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS notif_open_aggregate_uniq",
            state_operations=[
                migrations.AddConstraint(
                    model_name="notification",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(
                            ("read_at__isnull", True),
                            models.Q(("aggregate_key", ""), _negated=True),
                        ),
                        fields=("recipient_id", "aggregate_key"),
                        name="notif_open_aggregate_uniq",
                    ),
                ),
            ],
        ),
    ]
