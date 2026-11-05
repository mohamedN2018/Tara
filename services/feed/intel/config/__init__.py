"""The central ranking config, read side (02 section 8).

Every weight, cap, window and threshold the intel code uses is read from here,
never written as a literal in ranking, retrieval or eligibility code (owner
decision 20). Phase 3 ships the version-1 defaults of each surface as a JSON file
(``defaults/<surface>.json``); WP 4.1 adds the versioned store (``intel_ranking_config``),
its schema validation and the experiment variants on top of this same interface:

    cfg = config.for_surface("home")
    cfg.get("window.connections")        # 500
    cfg.section("retrieval")             # {"new_follow_hours": 24, ...}

A missing key is a programming error (``KeyError``): there is no silent default.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_DEFAULTS = Path(__file__).resolve().parent / "defaults"
SURFACES = ("home", "reels", "video", "groups")


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


@lru_cache(maxsize=len(SURFACES))
def _load(surface: str) -> dict:
    if surface not in SURFACES:
        raise KeyError(f"unknown surface {surface!r}")
    with (_DEFAULTS / f"{surface}.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def for_surface(surface: str, overrides: dict | None = None) -> SurfaceConfig:
    """The active config of ``surface`` (version-1 defaults until WP 4.1).

    ``overrides`` replaces whole top-level sections (tests and, later, experiment
    variants); the shared defaults are never mutated.
    """
    params = copy.deepcopy(_load(surface))
    if overrides:
        for key, value in overrides.items():
            if key not in params:
                raise KeyError(f"{surface}: unknown config section {key!r}")
            params[key] = {**params[key], **value} if isinstance(value, dict) else value
    return SurfaceConfig(surface, f"{surface}@{params['version']}", params)
