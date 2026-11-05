"""Backfill ``search_account_restriction`` from moderation's export (Tara
Intelligence 4b.20-B3), modelled on graph's ``intel_backfill_restrictions``.

A ``restrict`` or ``shadow`` decided before search consumed
``moderation.actioned`` would keep that author's posts in the trending counts
until the next decision. This reads ``/internal/v1/intel/export/restrictions/``
(every user case decided ``restrict`` / ``shadow`` that no appeal overturned)
and applies it with the export's ``as_of`` clock through the same newest-wins
writer as the event.

After a complete scan, an account search holds as restricted that moderation
no longer lists has no restriction standing (its ``reinstate`` was lost): it is
lifted, at the scan's start time. Safe to re-run. Prints counts only, never ids.

    python manage.py search_backfill_restrictions [--batch-size 200] [--rate 20] [--no-sweep]
"""

from __future__ import annotations

import time
import uuid

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from searchsvc import restrictions
from searchsvc.models import SearchAccountRestriction
from tara_common.auth import mint_internal_token

EXPORT_PATH = "/internal/v1/intel/export/restrictions/"


def _pages(limit: int, rate: float):
    url = f"{settings.MODERATION_INTERNAL_URL}{EXPORT_PATH}"
    gap = 1.0 / rate if rate > 0 else 0.0
    after = ""
    while True:
        began = time.monotonic()
        token = mint_internal_token(issuer="search", audience="moderation-internal")
        try:
            resp = requests.get(
                url,
                params={"after": after, "limit": limit},
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"moderation export unavailable ({exc}); run again") from exc
        data = resp.json()["data"]
        yield parse_datetime(data["as_of"]), data["items"]
        if not data.get("next"):
            return
        after = data["next"]
        wait = gap - (time.monotonic() - began)
        if wait > 0:
            time.sleep(wait)


class Command(BaseCommand):
    help = "Backfill search's account restrictions (restrict, shadow) from moderation."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--batch-size", type=int, default=200)
        parser.add_argument("--rate", type=float, default=20.0, help="requests per second")
        parser.add_argument("--no-sweep", action="store_true", help="never lift a restriction")

    def handle(self, *args, **options) -> None:
        listed, applied, started = set(), 0, None
        for as_of, items in _pages(options["batch_size"], options["rate"]):
            started = started or as_of
            for item in items:
                p = item.get("payload") or {}
                try:
                    account_id = uuid.UUID(str(p.get("account_id")))
                except ValueError:
                    continue
                if p.get("action") not in restrictions.RESTRICTING_ACTIONS:
                    continue
                listed.add(str(account_id))
                applied += restrictions.set_restriction(
                    account_id, p["action"], p.get("case_id"), as_of
                )

        swept = 0
        if not options["no_sweep"] and started is not None:
            held = SearchAccountRestriction.objects.filter(active=True).values_list(
                "account_id", flat=True
            )
            for account_id in [a for a in held if str(a) not in listed]:
                swept += restrictions.set_restriction(
                    account_id, restrictions.REINSTATE, None, started
                )
        active = SearchAccountRestriction.objects.filter(active=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"listed {len(listed)}, applied {applied}, swept {swept}, active {active}"
            )
        )
