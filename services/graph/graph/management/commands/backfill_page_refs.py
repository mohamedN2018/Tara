"""Fill graph's page read model from profile's page export (plan 08, track 2D).

Pages created before graph consumed ``page.created``/``page.updated`` are
missing from "Suggested pages" until this runs once. Reads
``/internal/v1/search/export/pages/`` (published, live pages, in the
``page.updated`` payload shape) and applies each row with the export's
``as_of`` clock, so an event newer than the export still wins. Safe to re-run.
"""

from __future__ import annotations

import time

import jwt
import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from graph.handlers import apply_page_state


def _token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "graph", "aud": "profile-internal", "iat": now, "exp": now + 60},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


class Command(BaseCommand):
    help = "Backfill graph's PageRef read model from profile's page export."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--batch-size", type=int, default=200)

    def handle(self, *args, **options) -> None:
        url = f"{settings.PROFILE_INTERNAL_URL}/internal/v1/search/export/pages/"
        after, applied = "", 0
        while True:
            try:
                resp = requests.get(
                    url,
                    params={"after": after, "limit": options["batch_size"]},
                    headers={"Authorization": f"Bearer {_token()}"},
                    timeout=15,
                )
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise CommandError(f"profile export unavailable ({exc}); run again") from exc
            data = resp.json()["data"]
            as_of = parse_datetime(data["as_of"])
            for item in data["items"]:
                applied += apply_page_state(item["id"], item["payload"], as_of)
            if not data.get("next"):
                break
            after = data["next"]
        self.stdout.write(self.style.SUCCESS(f"applied {applied} pages"))
