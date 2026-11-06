# Tara Intelligence R3 WP A2 (07 WP 4b.5; written by hand: data only, additive).
#
# Stores the three home@2c versions as DRAFTS, never active (activation changes live
# order and is a staff step with a reason, ``manage.py intel_config activate``;
# decision 25, For You as the Home default, is a separate owner step):
#
#   home@2c       home.v2c.json: home@2b + schema v4 (exposure multiplier, rotation
#                 floor, revisit exception, visit keys of ``session``, peek cap);
#                 mix.recommended 0.0 (the decision-4 control) plus the decision-23
#                 thin-inventory share 0.10, continuation off
#   home@2c-r15   the same with mix.recommended 0.15 and continuation into pools
#   home@2c-r30   the same with mix.recommended 0.30 and continuation into pools
#
# They take the next integer versions of ``home``; the label is in ``note``. Like
# intel/0006, each one writes an ``intel_ranking_config_change`` row (action
# ``created``, the diff against the active version) and no outbox event.
# Idempotent: a label already stored is skipped. home@1, home@2 and the home@2b
# drafts are not touched.

import copy
import json
from pathlib import Path

from django.db import migrations

DEFAULTS = Path(__file__).resolve().parent.parent / "config" / "defaults"
ARMS = (
    ("home@2c", 0.0, False),
    ("home@2c-r15", 0.15, True),
    ("home@2c-r30", 0.30, True),
)
REASON = "loaded by migration intel/0010 (R3 exposure and rotation variants, drafts)"


def _params(base: dict, share: float, continues: bool) -> dict:
    params = copy.deepcopy(base)
    params["mix"]["recommended"] = share
    params["continuation"]["pools"] = continues
    return params


def load(apps, schema_editor):
    from intel.config import schema, store

    Config = apps.get_model("intel", "RankingConfig")
    Change = apps.get_model("intel", "RankingConfigChange")
    with (DEFAULTS / "home.v2c.json").open(encoding="utf-8") as fh:
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
        ("intel", "0009_feed_session"),
    ]

    operations = [migrations.RunPython(load, unload)]
