# Roadmap 4.3/4.4 schema: three-state price, sale price, effective price, counters.
# Every new column is nullable or has a constant default (a metadata-only change in
# Postgres 11+). The generated `effective_price` column rewrites `listing` once;
# the table is small today. Checks and indexes follow in 0005-0007.

import django.db.models.functions.comparison
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0002_security_fixes"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="currency_unconfirmed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="sale_price",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=19, null=True),
        ),
        migrations.AddField(
            model_name="listing",
            name="inquiry_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="listing",
            name="price_type",
            field=models.CharField(
                choices=[("fixed", "Fixed price"), ("negotiable", "Negotiable"), ("free", "Free")],
                default="fixed",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="listing",
            name="price_unconfirmed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="search_text",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="listing",
            name="view_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="listing",
            name="price",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=19, null=True),
        ),
        migrations.AddField(
            model_name="listing",
            name="effective_price",
            field=models.GeneratedField(
                db_persist=True,
                expression=django.db.models.functions.comparison.Coalesce("sale_price", "price"),
                output_field=models.DecimalField(decimal_places=4, max_digits=19, null=True),
            ),
        ),
    ]
