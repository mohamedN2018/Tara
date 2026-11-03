# Existing rows first (roadmap 4.3), before any check constraint is added:
#  * price=0 -> negotiable with no price ("on request"), flagged for the seller;
#  * free-text currencies -> the allow-list, or the default and flagged;
#  * search_text filled for the trigram index.
# Same functions as `manage.py classify_zero_price_listings` / `normalise_currencies`.

from django.db import migrations


def forwards(apps, schema_editor):
    from marketplace import backfill

    listing = apps.get_model("marketplace", "Listing")
    backfill.classify_zero_price_listings(listing)
    backfill.normalise_currencies(listing)
    backfill.backfill_search_text(listing)


def backwards(apps, schema_editor):
    # Undo only the price move; 0003's reverse needs NOT NULL prices back.
    listing = apps.get_model("marketplace", "Listing")
    listing.objects.filter(price__isnull=True).update(price=0, price_type="fixed", sale_price=None)


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0003_catalog_schema"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
