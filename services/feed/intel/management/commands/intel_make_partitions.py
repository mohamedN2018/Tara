"""Create telemetry partitions ahead, drop the ones past retention (WP 2.2)."""

from django.core.management.base import BaseCommand

from intel.signals import partitions


class Command(BaseCommand):
    help = "Create intel_* partitions 7 days ahead and drop those past retention."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--ahead-days", type=int, default=partitions.AHEAD_DAYS)
        parser.add_argument("--no-drop", action="store_true", help="Create only.")

    def handle(self, *args, **options) -> None:
        made = partitions.make_partitions(ahead_days=options["ahead_days"])
        dropped = [] if options["no_drop"] else partitions.drop_expired()
        purged = partitions.purge_batches()
        self.stdout.write(
            f"ensured {len(made)} partitions, dropped {len(dropped)} {dropped}, "
            f"purged {purged} batch rows"
        )
