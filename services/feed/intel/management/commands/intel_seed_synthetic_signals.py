"""Backdated synthetic telemetry for development and benchmarks (WP 2.9).

For every account registered with a ``seed-*`` label, writes impressions, opens
and video watches over the last ``--days`` days, **directly** into
``intel_signal_event``: ``source=server``, ``data_origin=synthetic``, no ``ts``
clamp, ``received_at = occurred_at`` (so the rows land in the past partitions,
which are created as needed). ``--scale N`` multiplies the sessions per account
and day: ``--scale 10`` is the 10x telemetry volume WP 9.1 and WP 13.1 load.

Only content the account was authorized to receive is used: the items come from
its own feed rows (fan-out follows post's visibility rules), minus what it hid,
snoozed or muted, and an item is never "seen" before it was posted.

Refused unless ``INTEL_ACCEPT_SYNTHETIC=true`` outside production, and refused
when ``--days`` reaches past ``INTEL_SIGNAL_RETENTION_DAYS`` (the rows would be
dropped by the next retention run). No duration is invented: completions need a
real duration (``intel_media_ref``, WP 3.1), so only starts, progress and skips
are written for videos until then. Re-running adds rows; ``--replace`` first
deletes the synthetic server rows this command wrote.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from intel import ports
from intel.models import DataOrigin, EventType, ItemType, SignalSource, Surface, SyntheticAccount
from intel.signals import partitions, store, validate

# Shape of the generated behaviour. These describe the synthetic dataset only.
SESSIONS_PER_DAY = (0, 1, 1, 2, 3)  # drawn uniformly per account and day
ITEMS_PER_SESSION = (5, 20)
SECONDS_BETWEEN_ITEMS = (3, 15)
OPEN_RATE = 0.15
WATCH_RATE = 0.5
WATCH_SECONDS = (1, 90)
PROGRESS_EVERY_S = 5
VIDEO_TYPES = frozenset({"video", "reel"})
CHUNK = 5000
# Marks every row of this command (batch_id namespace), so --replace finds them.
NAMESPACE = uuid.UUID("5e1d7a2c-7c55-4a1b-9b0c-1a7a5ed00001")


def _uuid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


class Command(BaseCommand):
    help = "Write backdated synthetic telemetry for seed-* accounts (dev and staging only)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--days", type=int, default=60)
        parser.add_argument("--scale", type=int, default=1)
        parser.add_argument("--seed", type=int, default=2026)
        parser.add_argument("--limit-accounts", type=int, default=0)
        parser.add_argument("--replace", action="store_true")

    def handle(self, *args, **options) -> None:
        if settings.TARA_ENV == "production" or not settings.INTEL_ACCEPT_SYNTHETIC:
            raise CommandError(
                "Refused: synthetic telemetry needs INTEL_ACCEPT_SYNTHETIC=true outside production."
            )
        days, scale = options["days"], max(1, options["scale"])
        if days < 1:
            raise CommandError("--days must be at least 1.")
        if days >= settings.INTEL_SIGNAL_RETENTION_DAYS:
            raise CommandError(
                f"Refused: --days {days} reaches past INTEL_SIGNAL_RETENTION_DAYS="
                f"{settings.INTEL_SIGNAL_RETENTION_DAYS}; those rows would be dropped."
            )
        accounts = list(
            SyntheticAccount.objects.filter(label__startswith="seed-")
            .order_by("account_id")
            .values_list("account_id", flat=True)
        )
        if options["limit_accounts"]:
            accounts = accounts[: options["limit_accounts"]]
        if not accounts:
            raise CommandError("No seed-* accounts registered (intel_register_synthetic).")
        if options["replace"]:
            self.stdout.write(f"deleted {self._delete_previous()} earlier synthetic rows")

        now = datetime.now(UTC)
        start = now - timedelta(days=days)
        for offset in range(days + 1):
            partitions.ensure(partitions.SIGNALS, (start + timedelta(days=offset)).date())

        total, rows = 0, []
        for account in accounts:
            rng = random.Random(f"{options['seed']}:{account}")  # noqa: S311 - synthetic data
            feed_rows = ports.visible_feed_rows(account)
            if not feed_rows:
                continue
            for day in range(days):
                for _ in range(rng.choice(SESSIONS_PER_DAY) * scale):
                    at = start + timedelta(days=day, seconds=rng.randint(0, 86_399))
                    if at >= now:
                        continue
                    rows += self._session(rng, account, feed_rows, at, now)
                    if len(rows) >= CHUNK:
                        total += self._flush(rows)
                        rows = []
        total += self._flush(rows)
        self.stdout.write(
            f"wrote {total} synthetic rows for {len(accounts)} accounts over {days} days "
            f"(scale {scale})"
        )

    def _session(self, rng, account, feed_rows, at, now) -> list[store.SignalRow]:
        seen = [r for r in feed_rows if r[3] <= at]
        if not seen:
            return []
        session = _uuid(rng)
        batch = uuid.uuid5(NAMESPACE, f"{account}:{session}")
        out = []
        picks = rng.sample(seen, min(len(seen), rng.randint(*ITEMS_PER_SESSION)))

        def row(event_type, post_id, author_id, when, **extra):
            return store.SignalRow(
                account_id=account,
                event_type=event_type,
                item_type=ItemType.POST,
                item_id=post_id,
                author_id=author_id,
                source=SignalSource.SERVER,
                data_origin=DataOrigin.SYNTHETIC,
                occurred_at=when,
                received_at=when,
                client_event_id=_uuid(rng),
                batch_id=batch,
                session_id=session,
                surface=Surface.HOME,
                **extra,
            )

        for position, (post_id, author_id, kind, _created) in enumerate(picks):
            if at >= now:
                break
            out.append(row(EventType.FEED_IMPRESSION, post_id, author_id, at, position=position))
            if rng.random() < OPEN_RATE:
                at += timedelta(seconds=1)
                out.append(row(EventType.POST_OPEN, post_id, author_id, at))
            if kind in VIDEO_TYPES and rng.random() < WATCH_RATE:
                at += timedelta(seconds=1)
                out.append(row(EventType.VIDEO_START, post_id, author_id, at, play_index=1))
                watched_ms = rng.randint(*WATCH_SECONDS) * 1000
                if watched_ms < validate.SKIP_MAX_MS:
                    out.append(
                        row(
                            EventType.VIDEO_SKIP,
                            post_id,
                            author_id,
                            at,
                            watch_ms=watched_ms,
                            play_index=1,
                        )
                    )
                else:
                    for ms in range(
                        PROGRESS_EVERY_S * 1000, watched_ms + 1, PROGRESS_EVERY_S * 1000
                    ):
                        tick = at + timedelta(milliseconds=ms)
                        out.append(
                            row(
                                EventType.VIDEO_PROGRESS,
                                post_id,
                                author_id,
                                tick,
                                watch_ms=ms,
                                pos_ms=ms,
                                play_index=1,
                            )
                        )
                    at += timedelta(milliseconds=watched_ms)
            at += timedelta(seconds=rng.randint(*SECONDS_BETWEEN_ITEMS))
        return [r for r in out if r.occurred_at < now]

    def _flush(self, rows) -> int:
        if not rows:
            return 0
        with transaction.atomic():
            return store.copy_rows(rows)

    def _delete_previous(self) -> int:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                "DELETE FROM intel_signal_event WHERE data_origin = %s AND source = %s "
                "AND batch_id IS NOT NULL",
                [DataOrigin.SYNTHETIC, SignalSource.SERVER],
            )
            return cur.rowcount
