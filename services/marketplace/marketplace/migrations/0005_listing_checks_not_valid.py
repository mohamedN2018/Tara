# Price/currency checks added NOT VALID: new writes are checked at once, and the
# ACCESS EXCLUSIVE lock is held only for the catalogue update, not a table scan.
# 0006 validates the existing rows under a weaker lock.

from django.db import migrations, models

_CURRENCIES = (
    "AED",
    "BHD",
    "DZD",
    "EGP",
    "EUR",
    "GBP",
    "IQD",
    "JOD",
    "KWD",
    "LBP",
    "LYD",
    "MAD",
    "OMR",
    "QAR",
    "SAR",
    "SDG",
    "TND",
    "TRY",
    "USD",
)

_CHECKS = {
    "listing_price_nonneg": '"price" IS NULL OR "price" >= 0',
    "listing_sale_below_price": (
        '"sale_price" IS NULL OR ("price" IS NOT NULL AND "sale_price" >= 0'
        ' AND "sale_price" < "price")'
    ),
    "listing_price_type_valid": (
        "(\"price_type\" = 'free' AND \"price\" = 0 AND \"sale_price\" IS NULL)"
        " OR (\"price_type\" = 'fixed' AND \"price\" > 0)"
        " OR (\"price_type\" = 'negotiable' AND (\"price\" IS NULL OR \"price\" > 0))"
    ),
    "listing_currency_allowed": '"currency" IN ({})'.format(
        ", ".join(f"'{c}'" for c in _CURRENCIES)
    ),
}


def _add(name: str, sql: str) -> migrations.RunSQL:
    return migrations.RunSQL(
        f'ALTER TABLE "listing" ADD CONSTRAINT "{name}" CHECK ({sql}) NOT VALID',
        f'ALTER TABLE "listing" DROP CONSTRAINT IF EXISTS "{name}"',
    )


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0004_classify_prices"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[_add(name, sql) for name, sql in _CHECKS.items()],
            state_operations=[
                migrations.AddConstraint(
                    model_name="listing",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            ("price__isnull", True), ("price__gte", 0), _connector="OR"
                        ),
                        name="listing_price_nonneg",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="listing",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            ("sale_price__isnull", True),
                            models.Q(
                                ("price__isnull", False),
                                ("sale_price__gte", 0),
                                ("sale_price__lt", models.F("price")),
                            ),
                            _connector="OR",
                        ),
                        name="listing_sale_below_price",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="listing",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("price", 0), ("price_type", "free"), ("sale_price__isnull", True)),
                            models.Q(("price__gt", 0), ("price_type", "fixed")),
                            models.Q(
                                ("price_type", "negotiable"),
                                models.Q(("price__isnull", True), ("price__gt", 0), _connector="OR"),
                            ),
                            _connector="OR",
                        ),
                        name="listing_price_type_valid",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="listing",
                    constraint=models.CheckConstraint(
                        condition=models.Q(("currency__in", _CURRENCIES)),
                        name="listing_currency_allowed",
                    ),
                ),
            ],
        ),
    ]
