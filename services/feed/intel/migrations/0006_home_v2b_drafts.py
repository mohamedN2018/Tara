# Tara Intelligence 07 WP 4b.6 / 4b.10 (written by hand: data only, additive).
#
# Stores the three home@2b versions as DRAFTS, never active (activation changes live
# order and is a staff step with a reason, ``manage.py intel_config activate``):
#
#   home@2b       home.v2b.json: home@2 + pools, mix (recommended 0.0, the decision-4
#                 control, plus the decision-23 thin-inventory share 0.10),
#                 continuation off, first-page head TTL, diversity as home@2
#   home@2b-r15   the same with mix.recommended 0.15 and continuation into pools
#   home@2b-r30   the same with mix.recommended 0.30 and continuation into pools
#
# They take the next integer versions of ``home`` (3, 4 and 5 on a database holding
# home@1 and home@2); the label is in ``note``. Like intel/0004 (package loads), each
# one writes an ``intel_ranking_config_change`` row (action ``created``, the diff
# against the active version) and no outbox event: the staff actions that matter
# (activate, rollback) go through ``store`` and are audited in admin. Idempotent: a
# label already stored is skipped.

import copy
import json
from pathlib import Path

from django.db import migrations

DEFAULTS = Path(__file__).resolve().parent.parent / "config" / "defaults"
ARMS = (
    ("home@2b", 0.0, False),
    ("home@2b-r15", 0.15, True),
    ("home@2b-r30", 0.30, True),
)
REASON = "loaded by migration intel/0006 (WP 4b.6 variants, drafts)"


def _params(base: dict, share: float, continues: bool) -> dict:
    params = copy.deepcopy(base)
    params["mix"]["recommended"] = share
    params["continuation"]["pools"] = continues
    return params


def load(apps, schema_editor):
    from intel.config import schema, store

    Config = apps.get_model("intel", "RankingConfig")
    Change = apps.get_model("intel", "RankingConfigChange")
    with (DEFAULTS / "home.v2b.json").open(encoding="utf-8") as fh:
        base = json.load(fh)
    active = Config.objects.filter(surface="home", status="active").first()
    for label, share, continues in ARMS:
        if Config.objects.filter(surface="home", note=label).exists():
            continue
        latest = (
            Config.objects.filter(surface="home")
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        version = (latest or 0) + 1
        params = _params(base, share, continues)
        params.update({"surface": "home", "version": version})
        schema.check("home", params)
        Config.objects.create(
            surface="home",
            version=version,
            status="draft",
            params=params,
            schema_version=params["schema_version"],
            note=label,
        )
        Change.objects.create(
            surface="home",
            from_version=active.version if active else None,
            to_version=version,
            action="created",
            diff=store.diff(active.params, params) if active else [],
            reason=REASON,
        )


def unload(apps, schema_editor):
    """Drafts may be deleted (the trigger refuses only released versions)."""
    Config = apps.get_model("intel", "RankingConfig")
    Config.objects.filter(
        surface="home", status="draft", note__in=[label for label, _, _ in ARMS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("intel", "0005_content_integrity"),
    ]

    operations = [migrations.RunPython(load, unload)]
