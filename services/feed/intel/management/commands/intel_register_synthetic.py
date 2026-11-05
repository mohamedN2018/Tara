"""Register (or remove) synthetic and test accounts in ``intel_synthetic_account`` (WP 2.9).

The label decides the origin of every row those accounts produce: ``seed-*`` gives
``synthetic``, ``test-*`` gives ``test``. Refused unless this environment accepts
synthetic rows (``INTEL_ACCEPT_SYNTHETIC=true``, never in production).

    python manage.py intel_register_synthetic --label seed-2026-11 --manifest manifest.json
    python manage.py intel_register_synthetic --label test-integration --ids <uuid> <uuid>
    python manage.py intel_register_synthetic --remove --ids <uuid>
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from intel import origin
from intel.models import SyntheticAccount


def _ids_from_manifest(path: Path) -> list[str]:
    """``scripts/seed`` state: ``{"accounts": {"u001": {"id": ...}, ...}}``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    accounts = data.get("accounts", {}) if isinstance(data, dict) else {}
    return [a["id"] for a in accounts.values() if isinstance(a, dict) and a.get("id")]


class Command(BaseCommand):
    help = "Register synthetic (seed-*) or test (test-*) accounts for Tara Intelligence."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--label", help="seed-<name> or test-<name>")
        parser.add_argument("--ids", nargs="*", default=[])
        parser.add_argument("--manifest", help="a scripts/seed manifest.json")
        parser.add_argument("--remove", action="store_true", help="unregister the ids")

    def handle(self, *args, **options) -> None:
        if settings.TARA_ENV == "production" or not settings.INTEL_ACCEPT_SYNTHETIC:
            raise CommandError(
                "Refused: synthetic accounts are accepted only with INTEL_ACCEPT_SYNTHETIC=true "
                "outside production."
            )
        ids = list(options["ids"])
        if options["manifest"]:
            ids += _ids_from_manifest(Path(options["manifest"]))
        try:
            ids = sorted({str(uuid.UUID(str(i))) for i in ids})
        except ValueError as exc:
            raise CommandError(f"Not an account id: {exc}") from exc
        if not ids:
            raise CommandError("No account ids given (--ids or --manifest).")
        if options["remove"]:
            removed, _ = SyntheticAccount.objects.filter(account_id__in=ids).delete()
            origin.clear_cache()
            self.stdout.write(f"removed {removed} accounts")
            return
        label = options["label"] or ""
        try:
            SyntheticAccount(account_id=ids[0], label=label).full_clean(validate_unique=False)
        except ValidationError as exc:
            raise CommandError(f"Invalid label {label!r}: {exc.messages}") from exc
        stored = SyntheticAccount.objects.filter(account_id__in=ids)
        existing = {str(a) for a in stored.values_list("account_id", flat=True)}
        SyntheticAccount.objects.bulk_create(
            [SyntheticAccount(account_id=i, label=label) for i in ids if i not in existing]
        )
        updated = SyntheticAccount.objects.filter(account_id__in=existing).exclude(label=label)
        relabelled = updated.update(label=label)
        origin.clear_cache()
        self.stdout.write(
            f"registered {len(ids) - len(existing)} new, relabelled {relabelled}, "
            f"label {label} ({origin.origin_of_label(label)})"
        )
