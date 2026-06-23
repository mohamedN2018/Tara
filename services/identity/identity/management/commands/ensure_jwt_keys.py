"""Ensure the RS256 signing keypair exists.

Run by the container entrypoint BEFORE workers start, so every gunicorn worker
shares one key. In production, keys come from the secret manager (env) and this
command is a no-op.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand

from identity.keys import ensure_key_files


class Command(BaseCommand):
    help = "Generate the JWT signing keypair on disk if it does not already exist."

    def handle(self, *args, **options) -> None:
        if os.getenv("IDENTITY_JWT_PRIVATE_KEY") and os.getenv("IDENTITY_JWT_PUBLIC_KEY"):
            self.stdout.write("JWT keys provided via environment; nothing to generate.")
            return
        priv, _pub = ensure_key_files(settings.JWT_KEY_DIR)
        self.stdout.write(
            self.style.SUCCESS(
                f"JWT keys ready in {settings.JWT_KEY_DIR} ({len(priv)} bytes private)"
            )
        )
