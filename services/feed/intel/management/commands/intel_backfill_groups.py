"""Backfill intel_group_ref and intel_group_membership from profile's exports (WP 3.2).

python manage.py intel_backfill_groups [--kind K] [--after CURSOR] [--rate 20]
"""

from ._backfill import BackfillCommand


class Command(BackfillCommand):
    help = "Backfill intel_group_ref and intel_group_membership from profile's exports (WP 3.2)."
    kinds = (
        "groups",
        "group-members",
    )
