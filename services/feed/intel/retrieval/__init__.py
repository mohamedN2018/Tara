"""Stage 1 of the pipeline: the candidate inventory (02 section 6.1; WP 3.4).

``candidates(viewer, surface)`` merges the surface's sources, connections first, and
keeps one candidate per post (the first source that found it). The result is not
yet allowed to anybody: ``intel.eligibility.filter`` runs next, always.
"""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from .. import config
from ..config import SurfaceConfig
from . import sources
from .sources import CONNECTIONS, FOLLOW_PULL, GROUPS, REELS, VIDEO, Candidate

__all__ = ["CONNECTIONS", "FOLLOW_PULL", "GROUPS", "REELS", "VIDEO", "Candidate", "candidates"]


def _home(viewer, cfg, now):
    return [
        *sources.connections(viewer, cfg),
        *sources.follow_pull(viewer, cfg, now),
        *sources.groups(viewer, cfg, now),
    ]


def _typed(kind: str, surface_type: str):
    def build(viewer, cfg, now):
        window = cfg.get(f"window.{cfg.surface}")
        connected = sources.connections(viewer, cfg, types=(surface_type,))
        return connected + sources.public_pool(
            viewer, cfg, now, surface_type, window - len(connected)
        )

    build.__name__ = f"_{kind}"
    return build


SURFACES = {
    "home": _home,
    "reels": _typed(REELS, "reel"),
    "video": _typed(VIDEO, "video"),
    "groups": lambda viewer, cfg, now: sources.groups(viewer, cfg, now),
}


def candidates(
    viewer_id, surface: str, cfg: SurfaceConfig | None = None, now: datetime | None = None
) -> list[Candidate]:
    cfg = cfg or config.for_surface(surface)
    found = SURFACES[surface](str(viewer_id), cfg, now or timezone.now())
    seen: set[str] = set()
    out = []
    for c in found:
        if c.post_id not in seen:
            seen.add(c.post_id)
            out.append(c)
    return out
