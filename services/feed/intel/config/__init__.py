"""The central ranking config, read side (02 section 8).

Every weight, cap, window and threshold the intel code uses is read from here,
never written as a literal in ranking, retrieval or eligibility code (owner
decision 20). The values come from the surface's **active version** in the store
(``intel_ranking_config``, ``store.py``; WP 4.1), validated by ``schema.py``. The
version-1 defaults of each surface ship as ``defaults/<surface>.json`` (loaded by
migration ``intel/0004`` as version 1, and the fallback when the store is
unreadable). Experiment variants (WP 5.4) plug in behind this same interface:

    cfg = config.for_surface("home")
    cfg.get("window.connections")        # 500
    cfg.section("retrieval")             # {"new_follow_hours": 24, ...}

A missing key is a programming error (``KeyError``): there is no silent default.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from . import store
from .schema import SURFACES

__all__ = ["SURFACES", "SurfaceConfig", "for_surface", "store"]


@dataclass(frozen=True)
class SurfaceConfig:
    surface: str
    version: str
    params: dict

    def get(self, dotted: str) -> Any:
        node: Any = self.params
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"{self.version}: no config key {dotted!r}")
            node = node[part]
        return node

    def section(self, name: str) -> dict:
        value = self.get(name)
        if not isinstance(value, dict):
            raise KeyError(f"{self.version}: {name!r} is not a section")
        return copy.deepcopy(value)


def for_surface(surface: str, overrides: dict | None = None) -> SurfaceConfig:
    """The active config of ``surface`` (``store.resolve``: cached in process).

    ``overrides`` replaces keys of whole top-level sections (tests, offline
    evaluations); the cached params are never mutated.
    """
    if surface not in SURFACES:
        raise KeyError(f"unknown surface {surface!r}")
    version, params = store.resolve(surface)
    params = copy.deepcopy(params)
    if overrides:
        for key, value in overrides.items():
            if key not in params:
                raise KeyError(f"{surface}: unknown config section {key!r}")
            params[key] = {**params[key], **value} if isinstance(value, dict) else value
    return SurfaceConfig(surface, f"{surface}@{version}", params)


def for_version(surface: str, version: int) -> SurfaceConfig:
    """One stored version, whatever its status (offline comparisons, the parity test)."""
    return SurfaceConfig(surface, f"{surface}@{version}", store.load(surface, version))


def from_params(surface: str, params: dict) -> SurfaceConfig:
    """A config built from explicit params (merged over the package defaults)."""
    merged = store.merge(store.defaults(surface), params)
    return SurfaceConfig(surface, f"{surface}@{merged['version']}", merged)
