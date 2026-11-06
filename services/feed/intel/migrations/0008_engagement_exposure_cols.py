"""R3 WP A1 (06 section 13, 07 WP 4b.13): the exposure columns of
``intel_user_item_engagement`` and the client event type ``feed_dwell``.

``ADD COLUMN`` on the partitioned parent reaches every partition, existing and
future. Every column is either nullable without a default or ``NOT NULL`` with a
constant default, which PostgreSQL (>= 11) stores in the catalog: no rewrite of the
partitions. The model is unmanaged, so only the state is told.

``feed_dwell`` only adds a choice (state-only ``AlterField``; ``event_type`` is a
plain ``varchar(24)``, no CHECK constraint to change).
"""

from django.db import migrations, models

COLUMNS = (
    ("dwell_ms", "integer NOT NULL DEFAULT 0"),
    ("state", "smallint NULL"),
    ("consumed_dwell_only", "boolean NOT NULL DEFAULT false"),
    ("last_displayed_at", "timestamptz NULL"),
    ("visits", "smallint NOT NULL DEFAULT 0"),
)
FORWARD = "ALTER TABLE intel_user_item_engagement " + ", ".join(
    f"ADD COLUMN IF NOT EXISTS {name} {ddl}" for name, ddl in COLUMNS
)
REVERSE = "ALTER TABLE intel_user_item_engagement " + ", ".join(
    f"DROP COLUMN IF EXISTS {name}" for name, _ in reversed(COLUMNS)
)

EVENT_TYPES = [
    ("feed_impression", "Impression"),
    ("post_open", "Post opened"),
    ("video_start", "Video started"),
    ("video_progress", "Video progress"),
    ("video_complete", "Video completed"),
    ("video_rewatch", "Video rewatched"),
    ("video_skip", "Video skipped"),
    ("reel_view", "Reel viewed"),
    ("profile_visit", "Profile visited"),
    ("feed_dwell", "Feed dwell"),
    ("post_like", "Reacted"),
    ("post_unlike", "Reaction removed"),
    ("post_comment", "Commented"),
    ("post_share", "Shared"),
    ("post_save", "Saved"),
    ("post_unsave", "Unsaved"),
    ("post_report", "Reported"),
    ("follow", "Followed"),
    ("unfollow", "Unfollowed"),
    ("mute", "Muted"),
    ("unmute", "Unmuted"),
    ("block", "Blocked"),
    ("unblock", "Unblocked"),
    ("post_hide", "Hidden"),
    ("post_unhide", "Hide undone"),
    ("author_snooze", "Author snoozed"),
    ("author_unsnooze", "Snooze undone"),
    ("interested", "Interested"),
    ("not_interested", "Not interested"),
    ("more_like_this", "Show more like this"),
    ("less_like_this", "Show less like this"),
]


class Migration(migrations.Migration):
    dependencies = [("intel", "0007_impression_def")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(FORWARD, REVERSE)],
            state_operations=[
                migrations.AddField(
                    model_name="useritemengagement",
                    name="dwell_ms",
                    field=models.IntegerField(default=0),
                ),
                migrations.AddField(
                    model_name="useritemengagement",
                    name="state",
                    field=models.SmallIntegerField(null=True),
                ),
                migrations.AddField(
                    model_name="useritemengagement",
                    name="consumed_dwell_only",
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name="useritemengagement",
                    name="last_displayed_at",
                    field=models.DateTimeField(null=True),
                ),
                migrations.AddField(
                    model_name="useritemengagement",
                    name="visits",
                    field=models.SmallIntegerField(default=0),
                ),
            ],
        ),
        migrations.AlterField(
            model_name="signalevent",
            name="event_type",
            field=models.CharField(choices=EVENT_TYPES, max_length=24),
        ),
    ]
