"""WP 4c.9-B3 (08 section 7.12): ``intel_signal_event.impression_def``.

The impression rule is a stored-data definition (02 section 8.4): rule v1 is >= 50%
of the card for 1 s, rule v2 adds ">= 50% of the viewport covered by the card"
for tall cards. Each ``feed_impression`` row records the rule its client used, so
rates before and after never mix silently. NULL on every other row (server and bus
rows, other event types); a client that sends no ``idef`` is stored as 1.

``ADD COLUMN`` on the partitioned parent reaches every partition, existing and
future. A nullable column without a default is a catalog-only change: no rewrite
of the (large) partitions. The model is unmanaged, so only the state is told.
"""

from django.db import migrations, models

FORWARD = "ALTER TABLE intel_signal_event ADD COLUMN IF NOT EXISTS impression_def smallint NULL"
REVERSE = "ALTER TABLE intel_signal_event DROP COLUMN IF EXISTS impression_def"


class Migration(migrations.Migration):
    dependencies = [("intel", "0006_home_v2b_drafts")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(FORWARD, REVERSE)],
            state_operations=[
                migrations.AddField(
                    model_name="signalevent",
                    name="impression_def",
                    field=models.SmallIntegerField(null=True),
                )
            ],
        )
    ]
