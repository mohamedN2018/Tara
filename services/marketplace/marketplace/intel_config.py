"""The local copy of feed's ranking config for the marketplace surface (Tara
Intelligence WP 5.5). Handler and cache only: marketplace has no ranked surface
yet, so ``served`` is not called by any view (an R4 deviation).

Feed publishes ``intel.config.published`` with a surface's active params and, when
one runs, its experiment (``{key, salt, variants: [{name, pct, version, params}]}``).
This service keeps the newest per surface in ``intel_config`` (by ``published_at``,
then ``version``; an older or equal redelivery changes nothing) and serves from it:

- no row: the built-in defaults, which reproduce the constants this service used
  before R4 (``discovery@1``), so the output is unchanged (parity);
- a row and no experiment: the row's params over the defaults;
- an experiment: the viewer is bucketed with ``tara_common.bucketing.assign_variant``
  (the same function feed uses, so an account gets the same variant everywhere); its
  variant's params apply, the response meta says ``variant``, and the first time an
  account is served a variant ``intel.experiment.exposed`` is recorded in the outbox
  (``intel_exposure_seen`` keeps it to once per account and experiment), behind
  ``INTEL_EMIT_EXPOSURE_EVENTS``.

Params are numbers and booleans only. A value of the wrong type or out of its range
falls back to the default: a bad publish can never widen what a viewer is shown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tara_common.bucketing import assign_variant

from . import events
from .models import IntelConfig, IntelExposureSeen

logger = logging.getLogger("tara.marketplace.intel_config")

SURFACE = "marketplace"

#: Marketplace has no ranked surface yet (R4 deviation, results/r4-track-b.md): it
#: keeps the published config and its experiment so the first ranked surface can
#: serve from them, but no parameter is read and nothing is exposed today.
DEFAULTS: dict[str, tuple[object, object, object]] = {}


@dataclass(frozen=True)
class Served:
    """What a request serves: the params, and the experiment arm when one applies."""

    params: dict = field(default_factory=dict)
    variant: str | None = None
    experiment_key: str | None = None

    def get(self, key: str):
        return self.params[key]

    def meta(self) -> dict:
        return {"variant": self.variant} if self.variant else {}


def _lookup(params: dict, key: str):
    """``people.default_limit`` as a nested path or a dotted key; ``None`` when absent."""
    if not isinstance(params, dict):
        return None
    if key in params:
        return params[key]
    node: object = params
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _valid(key: str, value):
    default, low, high = DEFAULTS[key]
    if isinstance(default, bool):
        return value if isinstance(value, bool) else None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if low <= value <= high else None


def resolve(*layers: dict) -> dict:
    """The defaults, overridden in order by each layer's valid values."""
    out = {key: spec[0] for key, spec in DEFAULTS.items()}
    for layer in layers:
        for key in DEFAULTS:
            value = _valid(key, _lookup(layer or {}, key))
            if value is not None:
                out[key] = value
    if out.get("people.default_limit", 0) > out.get("people.max_limit", 0):
        out["people.default_limit"] = out["people.max_limit"]
    return out


def _variants(experiment) -> list[dict]:
    if not isinstance(experiment, dict):
        return []
    return [v for v in experiment.get("variants") or [] if isinstance(v, dict)]


def served(account_id: str | None, surface: str = SURFACE) -> Served:
    """The params this account is served on ``surface`` (one primary-key read)."""
    row = IntelConfig.objects.filter(surface=surface).first()
    if row is None:
        return Served(resolve())
    base = row.params if isinstance(row.params, dict) else {}
    experiment = row.experiment if isinstance(row.experiment, dict) else None
    if not experiment or not account_id:
        return Served(resolve(base))
    name = assign_variant(str(account_id), experiment)
    variant = next((v for v in _variants(experiment) if str(v.get("name")) == name), None)
    if variant is None:
        return Served(resolve(base))
    key = str(experiment.get("key"))
    out = Served(resolve(base, variant.get("params") or {}), name, key)
    _expose(str(account_id), key, str(name), surface)
    return out


def _expose(account_id: str, experiment_key: str, variant: str, surface: str) -> None:
    """``intel.experiment.exposed`` once per (account, experiment), in one transaction
    with its ``intel_exposure_seen`` row. A failure never fails the request."""
    if not getattr(settings, "INTEL_EMIT_EXPOSURE_EVENTS", True):
        return
    if IntelExposureSeen.objects.filter(
        account_id=account_id, experiment_key=experiment_key
    ).exists():
        return
    try:
        with transaction.atomic():
            IntelExposureSeen.objects.create(
                account_id=account_id, experiment_key=experiment_key, variant=variant
            )
            events.emit(
                "intel.experiment.exposed",
                subject_id=account_id,
                payload={
                    "experiment_key": experiment_key,
                    "account_id": account_id,
                    "variant": variant,
                    "surface": surface,
                    "exposed_at": timezone.now().isoformat(),
                },
                actor_id=account_id,
            )
    except IntegrityError:  # a concurrent first serve recorded it
        return
    except Exception:  # noqa: BLE001 - telemetry never fails a suggestion request
        logger.warning("experiment exposure not recorded", exc_info=True)


def _published_at(value) -> datetime | None:
    at = parse_datetime(str(value or ""))
    if at is not None and timezone.is_naive(at):
        at = timezone.make_aware(at, UTC)
    return at


def apply_published(payload: dict) -> bool:
    """Store a published config when it is newer than the one kept. True when stored."""
    surface = payload.get("surface")
    version = payload.get("version")
    at = _published_at(payload.get("published_at"))
    if surface != SURFACE:
        return False  # another service's surface
    if at is None:
        logger.warning("config event without published_at skipped")
        return False
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        logger.warning("config event without a valid version skipped")
        return False
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    experiment = payload.get("experiment") if isinstance(payload.get("experiment"), dict) else None
    with transaction.atomic():
        row = IntelConfig.objects.select_for_update().filter(surface=surface).first()
        if row is not None and (row.published_at, row.version) >= (at, version):
            return False
        IntelConfig.objects.update_or_create(
            surface=surface,
            defaults={
                "version": version,
                "params": params,
                "experiment": experiment,
                "published_at": at,
            },
        )
    return True
