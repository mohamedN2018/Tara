# Tara Intelligence R4 (04 WP 5.5, 6.5; 07 WP 6.5-B2; written by hand: data only,
# additive, idempotent).
#
# 1. ``discovery@1`` (defaults/discovery.json), stored ACTIVE: the people, page and
#    group suggestion constants graph and profile use today, exactly (parity), so the
#    ``intel.config.published`` contract has real params to vary under an experiment.
#    One ``intel_ranking_config_change`` row (``created``, then ``activated``); no
#    outbox event (``manage.py intel_config publish --surface discovery`` re-emits the
#    state for a consumer bootstrap).
# 2. Three home DRAFTS, never active (activation changes live order and is a staff
#    step with a reason; decision 25, For You as the Home default, is not flipped):
#
#      home@3       home.v3.json: home@2c + schema v5 (interest_rel, session_rel at
#                   weights.session 0.8, the R4 blocks); mix.recommended 0.0 (the
#                   decision-4 control) + the decision-23 thin-inventory share, no
#                   continuation; the exposure values are home@2c's, unchanged
#      home@3-r15   the same with mix.recommended 0.15 and continuation into pools
#      home@3-r30   the same with mix.recommended 0.30 and continuation into pools
#
# Each takes the next integer version of ``home``; the label is in ``note``. A label
# (or the discovery surface) already stored is skipped.

import copy
import json
from pathlib import Path

from django.db import migrations
from django.utils import timezone

DEFAULTS = Path(__file__).resolve().parent.parent / "config" / "defaults"
ARMS = (
    ("home@3", 0.0, False),
    ("home@3-r15", 0.15, True),
    ("home@3-r30", 0.30, True),
)
REASON = "loaded by migration intel/0012 (R4 discovery@1 parity; home@3 drafts)"


def _read(name: str) -> dict:
    with (DEFAULTS / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def load(apps, schema_editor):
    from intel.config import schema, store

    Config = apps.get_model("intel", "RankingConfig")
    Change = apps.get_model("intel", "RankingConfigChange")

    if not Config.objects.filter(surface="discovery").exists():
        params = _read("discovery.json")
        schema.check("discovery", params)
        Config.objects.create(
            surface="discovery",
            version=1,
            status="active",
            params=params,
            schema_version=params["schema_version"],
            note="discovery@1",
            activated_at=timezone.now(),
        )
        Change.objects.create(
            surface="discovery", from_version=None, to_version=1, action="created", reason=REASON
        )
        Change.objects.create(
            surface="discovery", from_version=None, to_version=1, action="activated", reason=REASON
        )

    base = _read("home.v3.json")
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
        params = copy.deepcopy(base)
        params["mix"]["recommended"] = share
        params["continuation"]["pools"] = continues
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
    Config = apps.get_model("intel", "RankingConfig")
    Change = apps.get_model("intel", "RankingConfigChange")
    # The drafts only. ``discovery@1`` was released (active): the immutability
    # trigger of intel/0004 never lets a released version be deleted or return to
    # draft, so it stays, and a later forward run skips it.
    for label, _share, _continues in ARMS:
        row = Config.objects.filter(surface="home", note=label, status="draft").first()
        if row is not None:
            Change.objects.filter(surface="home", to_version=row.version, reason=REASON).delete()
            row.delete()


class Migration(migrations.Migration):
    dependencies = [("intel", "0011_r4_interests_feedback")]

    operations = [migrations.RunPython(load, unload)]
