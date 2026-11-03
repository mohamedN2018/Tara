"""Re-emit profile.updated for every profile, to rebuild the people search index."""

from django.core.management.base import BaseCommand
from django.db import transaction

from profiles.models import UserProfile
from profiles.services import emit_profile_updated


class Command(BaseCommand):
    help = "Publish profile.updated for all profiles (rebuilds the people search index)."

    def handle(self, *args, **options):
        count = 0
        for profile in UserProfile.objects.filter(deleted_at__isnull=True).iterator():
            with transaction.atomic():
                emit_profile_updated(profile, changed=[])
            count += 1
        self.stdout.write(f"published {count} profiles")
