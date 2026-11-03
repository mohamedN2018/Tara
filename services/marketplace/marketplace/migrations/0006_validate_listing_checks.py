# VALIDATE CONSTRAINT takes SHARE UPDATE EXCLUSIVE: reads and writes continue
# while the existing rows are scanned. 0004 made every row pass.

from django.db import migrations

_NAMES = (
    "listing_price_nonneg",
    "listing_sale_below_price",
    "listing_price_type_valid",
    "listing_currency_allowed",
)


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0005_listing_checks_not_valid"),
    ]

    operations = [
        migrations.RunSQL(
            f'ALTER TABLE "listing" VALIDATE CONSTRAINT "{name}"', migrations.RunSQL.noop
        )
        for name in _NAMES
    ]
