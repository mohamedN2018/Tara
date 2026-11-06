"""R3 WP A1 (06 sections 4.3 and 13): ``intel_feed_session``, one row per Home visit.

A new, empty table: no lock on anything existing. It never holds item ids or topics.
Also an index on ``intel_block_pair(high)``: Home's visible rows now exclude blocked
authors from either side of the pair (a small table; a plain build is a short lock).
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("intel", "0008_engagement_exposure_cols")]

    operations = [
        migrations.CreateModel(
            name="FeedSession",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("account_id", models.UUIDField()),
                ("client_sid", models.UUIDField(null=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("new", "New visit"),
                            ("returning", "Returning"),
                            ("lapsed", "Lapsed"),
                        ],
                        max_length=10,
                    ),
                ),
                ("entry_surface", models.CharField(max_length=12)),
                ("started_at", models.DateTimeField()),
                ("last_activity_at", models.DateTimeField()),
                ("ended_at", models.DateTimeField(null=True)),
                ("first_pages", models.SmallIntegerField(default=0)),
                ("refreshes", models.SmallIntegerField(default=0)),
                ("displayed", models.IntegerField(default=0)),
                ("consumed", models.IntegerField(default=0)),
                ("new_since_count", models.SmallIntegerField(default=0)),
                ("intent", models.CharField(max_length=16, null=True)),
                ("head_overlap", models.FloatField(null=True)),
                (
                    "data_origin",
                    models.CharField(
                        choices=[
                            ("real", "Real"),
                            ("synthetic", "Synthetic (seed)"),
                            ("test", "Test fixture"),
                        ],
                        max_length=10,
                    ),
                ),
            ],
            options={
                "db_table": "intel_feed_session",
                "indexes": [
                    models.Index(
                        fields=["account_id", "-started_at"], name="intel_fsess_account_idx"
                    ),
                    models.Index(fields=["started_at"], name="intel_fsess_started_idx"),
                ],
            },
        ),
        migrations.AddIndex(
            model_name="blockpair",
            index=models.Index(fields=["high"], name="intel_block_high_idx"),
        ),
    ]
