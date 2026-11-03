"""Promote an existing, verified account to platform admin."""

from django.core.management.base import BaseCommand, CommandError

from identity.events import emit_security_event
from identity.models import Account, AccountRole


class Command(BaseCommand):
    help = "Grant the admin role to an existing, verified account."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, **options):
        email = options["email"].strip()
        account = Account.objects.filter(email__iexact=email).first()
        if account is None:
            raise CommandError(f"No account with email {email}. Register it first.")
        if not account.email_verified:
            raise CommandError(f"{email} has not verified its email.")
        if not account.is_usable:
            raise CommandError(f"{email} is not active (status: {account.status}).")

        _, created = AccountRole.objects.get_or_create(account=account, role=AccountRole.Role.ADMIN)
        if not created:
            self.stdout.write(f"{email} is already an admin.")
            return
        emit_security_event(account, "role_granted", {"role": "admin", "granted_by": "cli"})
        self.stdout.write(self.style.SUCCESS(f"{email} is now an admin (from the next token)."))
