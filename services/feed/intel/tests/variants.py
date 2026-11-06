"""The home@2b family (WP 4b.6), as stored by migration intel/0006 (drafts)."""

from __future__ import annotations

from intel import config
from intel.config import store
from intel.models import RankingConfig

CONTROL, R15, R30 = "home@2b", "home@2b-r15", "home@2b-r30"
# R4 (intel/0012): interest_rel, session_rel and the schema-5 blocks, drafts.
H3, H3_R15, H3_R30 = "home@3", "home@3-r15", "home@3-r30"


def version(label: str) -> int:
    return RankingConfig.objects.get(surface="home", note=label).version


def cfg(label: str = CONTROL, **sections) -> config.SurfaceConfig:
    """The stored variant, with whole-key overrides per section (tests only)."""
    base = config.for_version("home", version(label))
    params = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.params.items()}
    for name, value in sections.items():
        params[name] = {**params[name], **value} if isinstance(value, dict) else value
    return config.SurfaceConfig("home", base.version, params)


def activate(label: str) -> int:
    """Make the variant active in this (rolled-back) test transaction."""
    v = version(label)
    store.activate("home", v, reason="test")
    return v
