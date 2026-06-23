"""Seed a baseline set of marketplace categories (idempotent)."""

from django.core.management.base import BaseCommand

from marketplace.models import MarketplaceCategory

CATEGORIES = [
    ("electronics", "Electronics"),
    ("vehicles", "Vehicles"),
    ("furniture", "Furniture"),
    ("fashion", "Fashion"),
    ("home-garden", "Home & Garden"),
    ("property", "Property"),
    ("services", "Services"),
    ("other", "Other"),
]


class Command(BaseCommand):
    help = "Create the default marketplace categories."

    def handle(self, *args, **options) -> None:
        for i, (slug, name) in enumerate(CATEGORIES):
            _, created = MarketplaceCategory.objects.get_or_create(
                slug=slug, defaults={"name": name, "position": i}
            )
            self.stdout.write(("created " if created else "exists  ") + slug)
