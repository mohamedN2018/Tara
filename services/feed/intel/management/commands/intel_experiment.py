"""Manage A/B experiments (04 WP 5.4) until the dashboard (phase 12) ships.

    manage.py intel_experiment list
    manage.py intel_experiment create KEY --surface home --salt s1 \\
        --variant control:34:1 --variant r15:33:7 --variant r30:33:8 --actor <staff uuid>
    manage.py intel_experiment start KEY --reason "..." --actor <staff uuid>
    manage.py intel_experiment stop KEY --reason "..." --actor <staff uuid>

A variant is ``name:pct:version`` (the surface's config version it serves). Start and
stop are logged in ``intel_ranking_config_change`` and emit ``intel.config.changed``
and ``intel.config.published``. Starting needs a reason: it changes what real
accounts are served.
"""

from __future__ import annotations

import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from intel import experiments
from intel.config import SURFACES
from intel.models import Experiment


def _actor(value):
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise CommandError("--actor must be a staff account uuid") from exc


def _variant(raw: str) -> dict:
    parts = raw.split(":")
    if len(parts) != 3:
        raise CommandError(f"--variant {raw!r}: expected name:pct:version")
    name, pct, version = parts
    try:
        return {"name": name, "pct": float(pct), "version": int(version)}
    except ValueError as exc:
        raise CommandError(f"--variant {raw!r}: pct is a number, version an integer") from exc


class Command(BaseCommand):
    help = "List, create, start or stop experiments (WP 5.4)."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "create", "start", "stop"])
        parser.add_argument("key", nargs="?")
        parser.add_argument("--surface", choices=SURFACES)
        parser.add_argument("--salt", default="")
        parser.add_argument("--variant", action="append", default=[])
        parser.add_argument("--reason", default="")
        parser.add_argument("--actor", default="")

    def handle(self, action, key=None, **opts):
        if action == "list":
            for row in Experiment.objects.order_by("surface", "key"):
                self.stdout.write(
                    json.dumps(
                        {
                            "key": row.key,
                            "surface": row.surface,
                            "status": row.status,
                            "variants": row.variants,
                        }
                    )
                )
            return
        if not key:
            raise CommandError("an experiment key is required")
        try:
            if action == "create":
                if not opts["surface"] or not opts["salt"]:
                    raise CommandError("--surface and --salt are required")
                row = experiments.create(
                    key,
                    opts["surface"],
                    [_variant(v) for v in opts["variant"]],
                    salt=opts["salt"],
                    actor_id=_actor(opts["actor"]),
                )
                self.stdout.write(f"created {row.key} on {row.surface} (draft)")
                return
            if not opts["reason"].strip():
                raise CommandError("--reason is required to start or stop an experiment")
            fn = experiments.start if action == "start" else experiments.stop
            row = fn(key, actor_id=_actor(opts["actor"]), reason=opts["reason"])
            self.stdout.write(f"{row.key}: {row.status}")
        except experiments.ExperimentError as exc:
            raise CommandError(str(exc)) from exc
