"""Synthetic and real separation (docs/intelligence/02-architecture.md section 12.3).

- The origin of a row is decided by the ``intel_synthetic_account`` label only:
  ``seed-*`` gives ``synthetic``, ``test-*`` gives ``test``, everything else ``real``.
- A registered account is accepted as synthetic or test only while
  ``INTEL_ACCEPT_SYNTHETIC=true`` (dev and staging). When it is false, rows from a
  registered account are not stored at all (``Resolution.refused``): they can never
  be counted as real, and the readiness check fails while the table is non-empty.
- The bus-fed ranking tables that predate ``intel`` (``post_stats``, ``affinity``,
  ``reaction_state``) skip registered actors unless ``INTEL_SYNTHETIC_IN_RANKING=true``
  (dev only, where the whole dataset is synthetic).

Lookups are exact: an account registered a moment ago is synthetic at once in every
process, so its rows can never be stored as ``real`` in between. Only positive
answers are cached in-process (a registration is never undone except by account
deletion, which clears the cache); an unregistered account costs one primary-key
lookup per batch or event.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

from django.conf import settings

from .models import DataOrigin, SyntheticAccount

_POSITIVE_CAP = 10_000
_lock = threading.Lock()
_labels: dict[str, str] = {}  # registered accounts seen by this process


def clear_cache() -> None:
    """Forget the in-process positives (tests, and after the registry changes here)."""
    with _lock:
        _labels.clear()


def _norm(account_id) -> str | None:
    try:
        return str(uuid.UUID(str(account_id)))
    except (TypeError, ValueError):
        return None


def _lookup(keys: list[str]) -> dict[str, str]:
    """``{account: label}`` of the registered accounts among ``keys``."""
    found: dict[str, str] = {}
    missing = []
    with _lock:
        for key in keys:
            if key in _labels:
                found[key] = _labels[key]
            else:
                missing.append(key)
    if missing:
        rows = SyntheticAccount.objects.filter(account_id__in=missing).values_list(
            "account_id", "label"
        )
        fresh = {str(k): v for k, v in rows}
        if fresh:
            with _lock:
                if len(_labels) + len(fresh) > _POSITIVE_CAP:
                    _labels.clear()
                _labels.update(fresh)
        found.update(fresh)
    return found


def label_for(account_id) -> str | None:
    key = _norm(account_id)
    return _lookup([key]).get(key) if key else None


def origin_of_label(label: str) -> str:
    return DataOrigin.SYNTHETIC if label.startswith("seed-") else DataOrigin.TEST


@dataclass(frozen=True)
class Resolution:
    origin: str
    refused: bool = False  # registered, but this environment does not accept synthetic rows


def resolve(account_id) -> Resolution:
    """The ``data_origin`` of a row whose actor is ``account_id``."""
    label = label_for(account_id)
    if label is None:
        return Resolution(DataOrigin.REAL)
    if not settings.INTEL_ACCEPT_SYNTHETIC:
        return Resolution(origin_of_label(label), refused=True)
    return Resolution(origin_of_label(label))


def excluded_from_ranking(*account_ids) -> bool:
    """True when any actor is a registered synthetic or test account and this
    environment keeps them out of the ranking read models."""
    if settings.INTEL_SYNTHETIC_IN_RANKING:
        return False
    keys = [key for a in account_ids if a and (key := _norm(a)) is not None]
    return bool(keys) and bool(_lookup(keys))
