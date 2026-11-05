"""Manage the versioned ranking config (WP 4.1) until the dashboard (phase 12) ships.

    manage.py intel_config show home                  # active version + history
    manage.py intel_config validate home params.json  # schema check only
    manage.py intel_config create home params.json --note "..." --actor <staff uuid>
    manage.py intel_config activate home 2 --reason "..." --actor <staff uuid>
    manage.py intel_config rollback home --reason "..." --actor <staff uuid>

Every create, activation and rollback is logged in ``intel_ranking_config_change``
and emits ``intel.config.changed`` (admin's audit log). Active versions are
immutable: change a value by creating a new version.
"""

from __future__ import annotations

import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from intel.config import SURFACES, schema, store


def _actor(value):
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise CommandError("--actor must be a staff account uuid") from exc


class Command(BaseCommand):
    help = "Show, validate, create, activate or roll back ranking config versions."

    def add_arguments(self, parser):
        parser.add_argument(
            "action", choices=["show", "validate", "create", "activate", "rollback"]
        )
        parser.add_argument("surface", choices=SURFACES)
        parser.add_argument("arg", nargs="?", help="params file (validate/create) or version")
        parser.add_argument("--note", default="")
        parser.add_argument("--reason", default="")
        parser.add_argument("--actor", default="")

    def handle(self, action, surface, arg=None, **opts):
        try:
            if action == "show":
                version, params = store.resolve(surface)
                self.stdout.write(json.dumps({"active": version, "params": params}, indent=1))
                for row in store.history(surface, limit=20):
                    self.stdout.write(
                        f"{row['created_at']:%Y-%m-%d %H:%M} {row['action']:<12}"
                        f" {row['from_version']} -> {row['to_version']}"
                        f" ({len(row['diff'])} changes)"
                    )
                return
            if action in ("validate", "create"):
                if not arg:
                    raise CommandError("a params JSON file is required")
                with open(arg, encoding="utf-8") as fh:
                    params = json.load(fh)
                if action == "validate":
                    problems = schema.validate(surface, params)
                    if problems:
                        raise CommandError("\n".join(problems))
                    self.stdout.write("valid")
                    return
                version = store.create(
                    surface, params, actor_id=_actor(opts["actor"]), note=opts["note"]
                )
                self.stdout.write(f"created {surface}@{version} (draft)")
                return
            if not opts["reason"].strip():
                raise CommandError("--reason is required for an activation or a rollback")
            if action == "activate":
                if not (arg and arg.isdigit()):
                    raise CommandError("a version number is required")
                old = store.activate(
                    surface, int(arg), actor_id=_actor(opts["actor"]), reason=opts["reason"]
                )
                self.stdout.write(f"activated {surface}@{arg} (was {old})")
                return
            back = store.rollback(surface, actor_id=_actor(opts["actor"]), reason=opts["reason"])
            self.stdout.write(f"rolled back {surface} to version {back}")
        except (store.ConfigError, schema.ConfigInvalid) as exc:
            raise CommandError(str(exc)) from exc
