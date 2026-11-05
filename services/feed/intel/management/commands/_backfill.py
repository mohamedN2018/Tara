"""The shared body of the ``intel_backfill_*`` commands (WP 3.2)."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from intel import backfill


class BackfillCommand(BaseCommand):
    """Runs ``backfill.run`` for each of ``kinds`` and prints one JSON line per kind.

    A complete scan from the start also sweeps what the owner no longer has;
    ``--after`` resumes an interrupted scan from its last cursor (never swept).
    """

    kinds: tuple[str, ...] = ()

    def add_arguments(self, parser) -> None:
        parser.add_argument("--kind", choices=self.kinds, help="only this kind")
        parser.add_argument("--after", help="resume after this cursor (one --kind only)")
        parser.add_argument("--limit", type=int, default=200, help="items per page (max 500)")
        parser.add_argument("--rate", type=float, default=20.0, help="requests per second")
        parser.add_argument("--no-sweep", action="store_true", help="never switch rows off")

    def handle(self, *args, **opts) -> None:
        kinds = (opts["kind"],) if opts["kind"] else self.kinds
        if opts["after"] and len(kinds) != 1:
            raise CommandError("--after resumes one kind: pass --kind too")
        for kind in kinds:
            try:
                result = backfill.run(
                    kind,
                    after=opts["after"],
                    limit=opts["limit"],
                    rate=opts["rate"],
                    sweep=not opts["no_sweep"],
                    progress=self._progress,
                )
            except Exception as exc:  # report the cursor to resume from, then fail
                raise CommandError(
                    f"{kind}: {exc} (resume with --kind {kind} --after "
                    f"{getattr(self, '_cursor', None) or '<start>'})"
                ) from exc
            self._cursor = None
            self.stdout.write(json.dumps(result.as_dict()))

    def _progress(self, result: backfill.Result) -> None:
        self._cursor = result.last_cursor
        if result.pages % 20 == 0:
            self.stderr.write(f"{result.kind}: {result.items} items, cursor {result.last_cursor}")
