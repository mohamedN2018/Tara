"""Print viewers' eligible candidates for a surface (WP 3.4 / 3.5), for staff checks
and the WP 3.6 privacy integration. Ids, sources, reasons and per-rule drop counts
only; nothing about other accounts' behaviour.

    python manage.py intel_candidates <viewer> [<viewer> ...] [--surface home] [--adult]

A viewer is a UUID, or ``<uuid>:adult`` to treat that one viewer as an adult (the
integration passes what the viewer's own access token says). Without ``:adult`` or
``--adult`` a viewer is limited, as with no age claims (rule E9). One JSON object
per viewer, one per line.
"""

from __future__ import annotations

import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from intel import config, eligibility, retrieval

ADULT_CLAIMS = {"is_minor": False, "age_band": "25-34"}


def _viewer(token: str, adult: bool) -> eligibility.Viewer:
    raw, _, flag = token.partition(":")
    try:
        viewer_id = str(uuid.UUID(raw))
    except ValueError as exc:
        raise CommandError(f"viewer must be a UUID: {raw!r}") from exc
    if flag not in ("", "adult"):
        raise CommandError(f"unknown viewer flag {flag!r}")
    claims = ADULT_CLAIMS if adult or flag == "adult" else {}
    return eligibility.Viewer(viewer_id, **claims)


class Command(BaseCommand):
    help = "List viewers' eligible Tara Intelligence candidates as JSON lines."

    def add_arguments(self, parser) -> None:
        parser.add_argument("viewers", nargs="+")
        parser.add_argument("--surface", default="home", choices=sorted(retrieval.SURFACES))
        parser.add_argument(
            "--adult",
            action="store_true",
            help="treat every viewer as an adult (default: limited, as with no age claims)",
        )

    def handle(self, *args, **opts) -> None:
        surface = opts["surface"]
        cfg = config.for_surface(surface)
        for token in opts["viewers"]:
            viewer = _viewer(token, opts["adult"])
            found = retrieval.candidates(viewer.id, surface, cfg)
            result = eligibility.filter(viewer, found, cfg)
            by_source: dict[str, int] = {}
            for c in found:
                by_source[c.source] = by_source.get(c.source, 0) + 1
            self.stdout.write(
                json.dumps(
                    {
                        "viewer": viewer.id,
                        "surface": surface,
                        "config": cfg.version,
                        "limited": viewer.limited,
                        "found": by_source,
                        "dropped": dict(result.dropped),
                        "items": [
                            {"post_id": c.post_id, "source": c.source, "reason": c.reason}
                            for c in result.kept
                        ],
                    }
                )
            )
