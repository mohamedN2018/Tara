"""The experiment core (04 WP 5.4, 02 section 10.2), no UI.

An experiment targets one surface and maps each variant to a stored config version
of that surface: ``variants = [{name, pct, version}]`` with percentages summing to
at most 100 (the rest of the accounts are not in the experiment and get the active
version). Assignment is ``tara_common.bucketing.assign_variant`` over 10,000
buckets of ``f"{account_id}:{key}:{salt}"``: sticky, and the same function graph,
profile and marketplace run on the variants that ``intel.config.published``
carries, so an account gets the same variant in every service.

**Exposure is written at assignment** (02 section 10.2), on the account's first
serve of the surface under the experiment, with or without telemetry:
``intel_experiment_exposure`` gets one row per (experiment, account)
(``INSERT ... ON CONFLICT DO NOTHING``; a cache marker spares the statement on
later serves). Other services report theirs with ``intel.experiment.exposed.v1``
(``handlers.intel_on_experiment_exposed``).

At most one ``running`` experiment per surface (partial unique constraint). Start
and stop write an ``intel_ranking_config_change`` row (``experiment_started`` /
``experiment_stopped``), emit ``intel.config.changed`` and, behind
``INTEL_EMIT_R4_EVENTS``, ``intel.config.published`` with the surface's state, all
in one transaction. Nothing here starts an experiment on its own: ``manage.py
intel_experiment`` is a staff step with a reason.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone

from tara_common.bucketing import assign_variant

from . import config, origin
from .config import store
from .models import Experiment, RankingConfig

logger = logging.getLogger("tara.intel.experiments")

CACHE_TTL_S = 30.0
EXPOSED_MARK_TTL_S = 30 * 24 * 3600
_lock = threading.Lock()
_running: dict[str, tuple[float, dict | None]] = {}


class ExperimentError(Exception):
    """An experiment operation that is not allowed."""


@dataclass(frozen=True)
class Assignment:
    key: str
    variant: str
    version: int


def clear_cache() -> None:
    with _lock:
        _running.clear()
    store.clear_cache()


def _as_dict(row: Experiment) -> dict:
    return {
        "key": row.key,
        "surface": row.surface,
        "salt": row.salt,
        "variants": [
            {"name": v["name"], "pct": v["pct"], "version": int(v["version"])} for v in row.variants
        ],
    }


def running(surface: str) -> dict | None:
    """The surface's running experiment, read with the active config in one statement
    and cached with it (``store.running_experiment``): no query of its own."""
    found = store.running_experiment(surface)
    if not found:
        return None
    return {
        "key": found["key"],
        "surface": surface,
        "salt": found.get("salt") or "",
        "variants": [
            {"name": v["name"], "pct": v["pct"], "version": int(v["version"])}
            for v in found.get("variants") or []
        ],
    }


def assign(account_id, surface: str) -> Assignment | None:
    exp = running(surface)
    if exp is None:
        return None
    name = assign_variant(str(account_id), exp)
    if name is None:
        return None
    version = next(int(v["version"]) for v in exp["variants"] if v["name"] == name)
    return Assignment(exp["key"], name, version)


def config_for(account_id, surface: str, *, record: bool = True):
    """The config ``account_id`` is served on ``surface``: its variant's version under
    a running experiment (exposure recorded at this first serve), else the active one."""
    assignment = assign(account_id, surface)
    if assignment is None:
        return config.for_surface(surface)
    try:
        cfg = config.for_version(surface, assignment.version)
    except store.ConfigError:
        logger.warning("experiment %s names a missing version", assignment.key)
        return config.for_surface(surface)
    if record:
        record_exposure(assignment.key, account_id, assignment.variant, surface)
    return cfg


def _mark(key: str, account_id) -> str:
    return f"intel:expx:{key}:{account_id}"


def record_exposure(key: str, account_id, variant: str, surface: str, when=None) -> bool:
    """One row per (experiment, account); True when this call wrote it."""
    marker = _mark(key, account_id)
    try:
        if cache.get(marker):
            return False
    except Exception:  # noqa: BLE001 - the insert below is idempotent anyway
        logger.debug("exposure marker unreadable", exc_info=True)
    resolution = origin.resolve(account_id)
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO intel_experiment_exposure "
            "(experiment_key, account_id, variant, surface, first_exposed_at, data_origin) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            [key, str(account_id), variant, surface, when or timezone.now(), resolution.origin],
        )
        wrote = cur.rowcount == 1
    try:
        cache.set(marker, 1, EXPOSED_MARK_TTL_S)
    except Exception:  # noqa: BLE001 - the marker only spares a statement
        logger.debug("exposure marker not stored", exc_info=True)
    return wrote


# ---- staff operations (manage.py intel_experiment) ----------------------------------


def _check_variants(surface: str, variants: list[dict]) -> list[dict]:
    if not variants:
        raise ExperimentError("an experiment needs at least one variant")
    names, total, out = set(), 0.0, []
    versions = set(RankingConfig.objects.filter(surface=surface).values_list("version", flat=True))
    for v in variants:
        name = str(v.get("name") or "").strip()
        if not name or name in names:
            raise ExperimentError(f"variant names must be distinct and non-empty: {name!r}")
        pct = float(v.get("pct") or 0)
        if pct <= 0:
            raise ExperimentError(f"variant {name}: pct must be > 0")
        version = int(v.get("version") or 0)
        if version not in versions:
            raise ExperimentError(f"variant {name}: {surface}@{version} does not exist")
        names.add(name)
        total += pct
        out.append({"name": name, "pct": pct, "version": version})
    if total > 100.0 + 1e-9:
        raise ExperimentError(f"variant percentages sum to {total} (> 100)")
    return out


def create(key: str, surface: str, variants: list[dict], *, salt: str, actor_id=None, **extra):
    if surface not in config.SURFACES:
        raise ExperimentError(f"unknown surface {surface!r}")
    if Experiment.objects.filter(key=key).exists():
        raise ExperimentError(f"experiment {key} exists")
    return Experiment.objects.create(
        key=key,
        surface=surface,
        salt=salt[:16],
        variants=_check_variants(surface, variants),
        created_by=actor_id,
        **extra,
    )


def _log(row: Experiment, action: str, *, actor_id, reason: str) -> None:
    from .models import RankingConfigChange

    active = store._load_active(row.surface)  # noqa: SLF001 - same package
    to_v = active[0] if active else 1
    RankingConfigChange.objects.create(
        surface=row.surface,
        from_version=to_v,
        to_version=to_v,
        action=action,
        diff=[{"path": "experiment", "from": None, "to": row.key}],
        reason=(reason or "")[:500],
        actor_id=actor_id,
    )
    store.emit_changed(
        row.surface, action, to_v, to_v, actor_id=actor_id, reason=reason, experiment=row.key
    )


def start(key: str, *, actor_id=None, reason: str = "") -> Experiment:
    with transaction.atomic():
        row = Experiment.objects.select_for_update().filter(key=key).first()
        if row is None:
            raise ExperimentError(f"no experiment {key}")
        if row.status == Experiment.Status.RUNNING:
            raise ExperimentError(f"{key} is already running")
        if row.status == Experiment.Status.STOPPED:
            raise ExperimentError(f"{key} was stopped: create a new experiment")
        if Experiment.objects.filter(surface=row.surface, status="running").exists():
            raise ExperimentError(f"{row.surface} already has a running experiment")
        row.variants = _check_variants(row.surface, row.variants)
        row.status = Experiment.Status.RUNNING
        row.started_at = row.started_at or timezone.now()
        row.save(update_fields=["status", "started_at", "variants"])
        _log(row, "experiment_started", actor_id=actor_id, reason=reason)
        publish(row.surface)
        transaction.on_commit(clear_cache)
    return row


def stop(key: str, *, actor_id=None, reason: str = "") -> Experiment:
    with transaction.atomic():
        row = Experiment.objects.select_for_update().filter(key=key).first()
        if row is None:
            raise ExperimentError(f"no experiment {key}")
        if row.status not in (Experiment.Status.RUNNING, Experiment.Status.PAUSED):
            raise ExperimentError(f"{key} is {row.status}: only a running experiment stops")
        row.status = Experiment.Status.STOPPED
        row.ends_at = timezone.now()
        row.save(update_fields=["status", "ends_at"])
        _log(row, "experiment_stopped", actor_id=actor_id, reason=reason)
        publish(row.surface)
        transaction.on_commit(clear_cache)
    return row


# ---- intel.config.published (WP 5.5) -------------------------------------------------


def published_payload(surface: str, *, now=None) -> dict:
    """The surface's active params plus its running experiment's variants, read from the
    database (not the process caches: this runs inside the changing transaction)."""
    active = store._load_active(surface)  # noqa: SLF001
    base = store.defaults(surface)
    version, params = (active[0], store.merge(base, active[1])) if active else (1, base)
    exp = Experiment.objects.filter(surface=surface, status=Experiment.Status.RUNNING).first()
    experiment = None
    if exp is not None:
        experiment = {
            "key": exp.key,
            "salt": exp.salt,
            "variants": [
                {
                    "name": v["name"],
                    "pct": float(v["pct"]),
                    "version": int(v["version"]),
                    "params": store.load(surface, int(v["version"])),
                }
                for v in exp.variants
            ],
        }
    return {
        "surface": surface,
        "version": int(version),
        "params": params,
        "published_at": (now or timezone.now()).isoformat(),
        "experiment": experiment,
    }


def publish(surface: str) -> bool:
    """Emit ``intel.config.published`` for ``surface`` in the caller's transaction."""
    from django.conf import settings

    if not getattr(settings, "INTEL_EMIT_R4_EVENTS", True):
        return False
    from feed.events import PRODUCER
    from feed.models import OutboxEvent

    from tara_events.envelope import EventEnvelope
    from tara_events.outbox import record_event

    with transaction.atomic():
        record_event(
            OutboxEvent,
            EventEnvelope(
                event_type="intel.config.published",
                payload=published_payload(surface),
                subject_id=surface,
                producer=PRODUCER,
                partition_key=f"intel.config:{surface}",
            ),
        )
    return True
