"""Notification v2 columns and the actor table (roadmap 2.14 and 2.16).

Every new column has a constant default (``now()`` is stable, not volatile), so
PostgreSQL adds them without rewriting the table. Indexes come in 0005,
built concurrently, after 0004 has backfilled the old rows.
"""

import django.db.models.deletion
import django.db.models.functions.datetime
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0002_push_subscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="actor_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="notification",
            name="aggregate_key",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="notification",
            name="category",
            field=models.CharField(blank=True, default="", max_length=24),
        ),
        migrations.AddField(
            model_name="notification",
            name="data",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="notification",
            name="last_event_at",
            field=models.DateTimeField(
                db_default=django.db.models.functions.datetime.Now(),
                default=django.utils.timezone.now,
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="recent_actor_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="notification",
            name="resolution",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="notification",
            name="target_ref",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="notification",
            name="visible_in_app",
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="message_previews",
            field=models.BooleanField(db_default=True, default=True),
        ),
        # A new, empty table: its index and constraint cost nothing to build.
        migrations.CreateModel(
            name="NotificationActor",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("actor_id", models.UUIDField()),
                ("last_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "notification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="actors",
                        to="notifications.notification",
                    ),
                ),
            ],
            options={
                "db_table": "notification_actor",
                "indexes": [models.Index(fields=["actor_id"], name="notif_actor_idx")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("notification", "actor_id"), name="notif_actor_uniq"
                    )
                ],
            },
        ),
    ]
