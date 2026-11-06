"""The versioned ranking config store (02 sections 8.1, 8.5; WP 4.1).

- ``intel_ranking_config`` holds every version of every surface; a version is
  immutable once it leaves ``draft`` (model guard + DB trigger, ``intel/0004``).
- Exactly one version per surface is ``active`` (partial unique constraint).
- Every create, activation and rollback writes one ``intel_ranking_config_change``
  row (JSON diff + free-text reason) and emits ``intel.config.changed`` through
  the outbox **in the same transaction** (admin turns it into an ``AuditEntry``;
  the reason stays here, the event says only ``reason_present``).
- Params are validated (``schema.check``) on create and again on activation.

Resolution (``resolve``): an in-process cache of the active version per surface,
refreshed every ``ACTIVE_TTL_S`` seconds (versions are immutable, so only the
pointer can go stale). A failed read keeps the last good config, else the package
defaults (``defaults/<surface>.json``, which are the version-1 params).
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import schema

logger = logging.getLogger("tara.intel.config")

DEFAULTS_DIR = Path(__file__).resolve().parent / "defaults"
ACTIVE_TTL_S = 30.0
EVENT = "intel.config.changed"

_lock = threading.Lock()
_active: dict[str, tuple[float, int, dict]] = {}  # surface -> (expires, version, params)
# R4 (WP 5.4): the surface's running experiment, read in the same statement as the
# active version and cached with it (no extra query on a feed request).
_running: dict[str, dict | None] = {}
_ACTIVE_SQL = """
SELECT c.version, c.params,
       (SELECT json_build_object('key', e.key, 'salt', e.salt, 'variants', e.variants)
          FROM intel_experiment e WHERE e.surface = c.surface AND e.status = 'running' LIMIT 1)
FROM intel_ranking_config c WHERE c.surface = %s AND c.status = 'active'
"""


class ConfigError(Exception):
    """A store operation that is not allowed (unknown version, not a draft, ...)."""


# ---- package defaults -------------------------------------------------------------------


@lru_cache(maxsize=16)
def _read_defaults(name: str) -> dict:
    with (DEFAULTS_DIR / f"{name}.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def defaults(surface: str, version: int = 1) -> dict:
    """The params a surface ships with (``home`` also ships ``home.v2.json``)."""
    if surface not in schema.SURFACES:
        raise KeyError(f"unknown surface {surface!r}")
    name = surface if version == 1 else f"{surface}.v{version}"
    return copy.deepcopy(_read_defaults(name))


def merge(base: dict, top: dict) -> dict:
    """``top`` over ``base``, section by section. A stored version keeps every key it
    defines; a section it predates (a later code release added it) comes from the
    package defaults, so a release can add a block without a new version."""
    out = copy.deepcopy(base)
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **copy.deepcopy(value)}
        else:
            out[key] = copy.deepcopy(value)
    return out


# ---- diff -------------------------------------------------------------------------------


def diff(old: Any, new: Any, path: str = "") -> list[dict]:
    """``[{path, from, to}]`` for every leaf that differs (dotted paths)."""
    if isinstance(old, dict) and isinstance(new, dict):
        out: list[dict] = []
        for key in sorted(set(old) | set(new)):
            sub = f"{path}.{key}" if path else str(key)
            if key not in old:
                out.append({"path": sub, "from": None, "to": new[key]})
            elif key not in new:
                out.append({"path": sub, "from": old[key], "to": None})
            else:
                out += diff(old[key], new[key], sub)
        return out
    return [] if old == new else [{"path": path, "from": old, "to": new}]


# ---- resolution -------------------------------------------------------------------------


def clear_cache() -> None:
    with _lock:
        _active.clear()
        _running.clear()


def _json(value):
    # Django's raw cursor returns json / jsonb as text.
    return json.loads(value) if isinstance(value, str) else value


def _load_active(surface: str, with_experiment: bool = False):
    """``(version, params)`` of the active row, or None. ``with_experiment``: one
    statement that also returns the running experiment (``(version, params, exp)``)."""
    from ..models import RankingConfig

    if with_experiment:
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute(_ACTIVE_SQL, [surface])
            row = cur.fetchone()
        return (row[0], _json(row[1]), _json(row[2])) if row else None
    row = (
        RankingConfig.objects.filter(surface=surface, status=RankingConfig.Status.ACTIVE)
        .values_list("version", "params")
        .first()
    )
    return (row[0], row[1]) if row else None


def resolve(surface: str) -> tuple[int, dict]:
    """``(version, params)`` of the surface's active config, merged over its defaults."""
    now = time.monotonic()
    with _lock:
        hit = _active.get(surface)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    try:
        found = _load_active(surface, with_experiment=True)
    except Exception:  # noqa: BLE001 - a config read never breaks a feed request
        if hit:
            logger.warning("ranking config unreadable; keeping %s@%s", surface, hit[1])
            return hit[1], hit[2]
        logger.warning("ranking config unreadable; using package defaults for %s", surface)
        base = defaults(surface)
        return int(base["version"]), base
    base = defaults(surface)
    if found is None:
        version, params, experiment = int(base["version"]), base, None
    else:
        version, params = found[0], merge(base, found[1])
        experiment = found[2] if len(found) > 2 else None
    with _lock:
        _active[surface] = (now + ACTIVE_TTL_S, version, params)
        _running[surface] = experiment
    return version, params


def running_experiment(surface: str) -> dict | None:
    """The surface's running experiment ``{key, salt, variants}`` (cached with the
    active version, ``ACTIVE_TTL_S``), or None."""
    resolve(surface)
    with _lock:
        return _running.get(surface)


def load(surface: str, version: int) -> dict:
    """The params of one stored version (merged over the defaults), any status."""
    from ..models import RankingConfig

    row = RankingConfig.objects.filter(surface=surface, version=version).first()
    if row is None:
        raise ConfigError(f"no config {surface}@{version}")
    return merge(defaults(surface), row.params)


# ---- writes -----------------------------------------------------------------------------


def emit_changed(
    surface: str, action: str, from_v, to_v, *, actor_id, reason: str, experiment=None
) -> None:
    if not getattr(settings, "INTEL_EMIT_CONFIG_CHANGED", True):
        return
    from feed.events import PRODUCER
    from feed.models import OutboxEvent

    from tara_events.envelope import EventEnvelope
    from tara_events.outbox import record_event

    record_event(
        OutboxEvent,
        EventEnvelope(
            event_type=EVENT,
            payload={
                "surface": surface,
                "action": action,
                "from_version": from_v,
                "to_version": to_v,
                "experiment": experiment,
                "reason_present": bool((reason or "").strip()),
            },
            subject_id=f"{surface}@{to_v}",
            producer=PRODUCER,
            actor_id=str(actor_id) if actor_id else None,
            partition_key=f"intel.config:{surface}",
        ),
    )


def _log(surface, action, from_v, to_v, *, diff_rows, actor_id, reason) -> None:
    from ..models import RankingConfigChange

    RankingConfigChange.objects.create(
        surface=surface,
        from_version=from_v,
        to_version=to_v,
        action=action,
        diff=diff_rows,
        reason=(reason or "")[:500],
        actor_id=actor_id,
    )
    emit_changed(surface, action, from_v, to_v, actor_id=actor_id, reason=reason or "")


def _after_commit_clear() -> None:
    clear_cache()
    transaction.on_commit(clear_cache)


def create(surface: str, params: dict, *, actor_id=None, note: str = "", reason: str = "") -> int:
    """Store ``params`` as the next draft version of ``surface``. Returns the version.

    ``params`` is the full version (every required block); it is validated first and
    never stored when invalid."""
    from ..models import RankingConfig

    params = copy.deepcopy(params)
    with transaction.atomic():
        latest = (
            RankingConfig.objects.select_for_update()
            .filter(surface=surface)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        version = (latest or 0) + 1
        params.update({"surface": surface, "version": version})
        params.setdefault("schema_version", schema.SCHEMA_VERSION)
        schema.check(surface, params)
        RankingConfig.objects.create(
            surface=surface,
            version=version,
            params=params,
            schema_version=params["schema_version"],
            note=(note or "")[:300],
            created_by=actor_id,
        )
        base = _load_active(surface)
        _log(
            surface,
            "created",
            base[0] if base else None,
            version,
            diff_rows=diff(base[1], params) if base else [],
            actor_id=actor_id,
            reason=reason,
        )
    return version


def update_draft(surface: str, version: int, params: dict) -> None:
    from ..models import RankingConfig

    with transaction.atomic():
        row = (
            RankingConfig.objects.select_for_update()
            .filter(surface=surface, version=version)
            .first()
        )
        if row is None:
            raise ConfigError(f"no config {surface}@{version}")
        if row.status != RankingConfig.Status.DRAFT:
            raise ConfigError(f"{surface}@{version} is {row.status}: only a draft can change")
        params = {**copy.deepcopy(params), "surface": surface, "version": version}
        params.setdefault("schema_version", schema.SCHEMA_VERSION)
        schema.check(surface, params)
        row.params = params
        row.save(update_fields=["params"])


def _switch(surface: str, version: int, *, action: str, actor_id, reason: str) -> int | None:
    from ..models import RankingConfig

    with transaction.atomic():
        rows = {
            r.version: r for r in RankingConfig.objects.select_for_update().filter(surface=surface)
        }
        target = rows.get(version)
        if target is None:
            raise ConfigError(f"no config {surface}@{version}")
        schema.check(surface, target.params)  # an invalid version is never activated
        current = next((r for r in rows.values() if r.status == "active"), None)
        if current is not None and current.version == version:
            raise ConfigError(f"{surface}@{version} is already active")
        if current is not None:
            current.status = RankingConfig.Status.ARCHIVED
            current.save(update_fields=["status"])
        target.status = RankingConfig.Status.ACTIVE
        target.activated_at = timezone.now()
        target.save(update_fields=["status", "activated_at"])
        from_v = current.version if current else None
        _log(
            surface,
            action,
            from_v,
            version,
            diff_rows=diff(current.params, target.params) if current else [],
            actor_id=actor_id,
            reason=reason,
        )
        # WP 5.5: consumers outside feed get the new active params (and the running
        # experiment's variants) in the same transaction.
        from .. import experiments

        experiments.publish(surface)
        _after_commit_clear()
        return from_v


def activate(surface: str, version: int, *, actor_id=None, reason: str = "") -> int | None:
    """Make ``version`` the surface's active config (the old one is archived).
    Returns the version it replaced."""
    return _switch(surface, version, action="activated", actor_id=actor_id, reason=reason)


def rollback(surface: str, *, actor_id=None, reason: str = "") -> int:
    """Re-activate the version the current one replaced. Returns that version."""
    from ..models import RankingConfigChange

    current = _load_active(surface)
    if current is None:
        raise ConfigError(f"{surface} has no active config")
    last = (
        RankingConfigChange.objects.filter(
            surface=surface,
            to_version=current[0],
            action__in=["activated", "rolled_back"],
            from_version__isnull=False,
        )
        .order_by("-created_at")
        .first()
    )
    if last is None:
        raise ConfigError(f"{surface}@{current[0]} replaced nothing: no rollback target")
    _switch(surface, last.from_version, action="rolled_back", actor_id=actor_id, reason=reason)
    return last.from_version


def history(surface: str, limit: int = 50) -> list[dict]:
    from ..models import RankingConfigChange

    return list(
        RankingConfigChange.objects.filter(surface=surface)
        .order_by("-created_at")
        .values("action", "from_version", "to_version", "diff", "reason", "actor_id", "created_at")[
            :limit
        ]
    )
