"""Backfill account state from its owners (WP 3.2 / 3.3):

- ``accounts``: author_ref's lifecycle (deactivated, suspended; rule E6) from
  identity's export of the accounts that are not active;
- ``restrictions``: intel_account_restriction (rule E11) from moderation's export
  of the standing user ``restrict`` / ``shadow`` decisions.

python manage.py intel_backfill_accounts [--kind K] [--after CURSOR] [--rate 20] [--no-sweep]
"""

from ._backfill import BackfillCommand


class Command(BackfillCommand):
    help = "Backfill author lifecycle (identity) and account restrictions (moderation)."
    kinds = ("accounts", "restrictions")
