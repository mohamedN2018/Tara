"""Seed synthetic DEVELOPMENT accounts.

These are obviously-fake local accounts for development only — NOT production
data. Refuses to run unless DEBUG is on.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from identity.models import Account

DEV_ACCOUNTS = [
    ("demo@tara.local", "DevPassw0rd!"),
    ("seller@tara.local", "DevPassw0rd!"),
    ("admin@tara.local", "DevPassw0rd!"),
]


class Command(BaseCommand):
    help = "Create synthetic development accounts (DEBUG only)."

    def handle(self, *args, **options) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_dev_data refuses to run with DEBUG=False.")
        for email, password in DEV_ACCOUNTS:
            account, created = Account.objects.get_or_create(
                email=email,
                defaults={
                    "status": Account.Status.ACTIVE,
                    "email_verified": True,
                    "is_staff": email.startswith("admin"),
                    "is_superuser": email.startswith("admin"),
                },
            )
            if created:
                account.set_password(password)
                account.save()
                self.stdout.write(self.style.SUCCESS(f"created {email}"))
            else:
                self.stdout.write(f"exists  {email}")
