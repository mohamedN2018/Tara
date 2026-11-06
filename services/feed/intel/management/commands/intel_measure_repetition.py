"""The repetition harness (07 WP 4b.1; 06 §1.1): how much Home repeats, measured.

    python manage.py intel_measure_repetition [--variant home@N] [--users 20]
        [--opens 4] [--pages 3] [--modes for_you,recent] [--clock-offset 1,6,24,72,168]
        [--crawl-pages 80] [--hot-url redis://redis-hot:6379/9]

Usually run from the host through ``scripts/intel/measure_repetition.py``.

How it stays harmless:

- **read-only SQL**: everything runs in one transaction opened with
  ``SET TRANSACTION READ ONLY`` and rolled back at the end, so no write can land
  (the author age capture of WP 4b.14 is switched off for the run);
- **throwaway Redis**: ranking sessions, first-page heads and the pools a variant
  needs go to a separate ``redis-hot`` database (``--hot-url``, default db 9 of the
  configured host), never the live one; the harness refuses the live URL;
- **any stored version, never activated**: ``--variant home@N`` ranks under that
  stored config (any status) by patching the resolver in this process only;
- **no account ids** in the output: viewers are counted, never named. Viewers are
  treated as adults (``is_minor`` false, an adult band), as the phase-4 probe did.

Viewers are chosen by query at run time: accounts with feed rows whose eligible
candidates under the variant number at least ``--min-candidates`` (60, three pages),
taken in a fixed pseudo-random order (``md5`` of the id) so runs are repeatable.

``--simulate-display`` (R3 WP A9) measures rotation with a simulated display: the
visit rows the first pages write (``intel_feed_session``) need a writable
transaction, so this run is **not** read-only but is still **always rolled back**,
and the command then asserts that no visit or signal row of the chosen viewers is
left. The displays go to the throwaway ledger through ``exposure.append_records``
at the simulated clock, never through the SQL ingest, so synthetic display never
reaches real analytics. Without the flag, the run stays read-only and the visit
rows are skipped (``session_ctx._write_rows``).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from contextlib import ExitStack
from datetime import timedelta
from unittest import mock
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext, override_settings
from django.utils import timezone

from intel import config, eligibility, repetition

ADULT = {"is_minor": False, "age_band": "25-34"}
CONNECTED_REASONS = frozenset({"self", "friend", "follow"})
DISCOVERY_SOURCE = "discovery"


class _Rollback(Exception):
    pass


def _hot_url(explicit: str | None) -> str:
    live = settings.CACHES["hot"]["LOCATION"]
    if explicit:
        url = explicit
    else:
        parts = urlsplit(live)
        url = urlunsplit((parts.scheme, parts.netloc, "/9", "", ""))
    if url.rstrip("/") == live.rstrip("/"):
        raise CommandError("the harness never writes to the live redis-hot database")
    return url


def _deep(base: dict, top: dict) -> dict:
    out = dict(base)
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep(out[key], value)
        else:
            out[key] = value
    return out


def _variant_patch(variant: str | None, override: dict | None = None):
    """``(label, patcher)``: rank under ``home@N`` without activating it. ``override``
    (``--override``, tuning runs only) is merged over its params and validated."""
    if not variant:
        if override:
            raise CommandError("--override needs --variant")
        return config.for_surface("home").version, None
    surface, _, number = variant.partition("@")
    if surface != "home" or not number.isdigit():
        raise CommandError("--variant must look like home@N")
    stored = config.for_version("home", int(number))
    if override:
        from intel.config import schema

        params = _deep(stored.params, override)
        schema.check("home", params)
        stored = config.SurfaceConfig("home", f"{stored.version}+override", params)
    real = config.for_surface

    def patched(name, overrides=None):
        if name != "home":
            return real(name, overrides)
        params = dict(stored.params)
        for key, value in (overrides or {}).items():
            params[key] = {**params[key], **value} if isinstance(value, dict) else value
        return config.SurfaceConfig("home", stored.version, params)

    return stored.version, mock.patch("intel.config.for_surface", side_effect=patched)


def _q(sql: str, params=None) -> list[tuple]:
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchall()


def _population() -> dict:
    """The population line (06 §1), by query: what feed_db can say about accounts."""
    out = {}
    out["recipients"] = _q("SELECT count(DISTINCT recipient_id) FROM feed_item")[0][0]
    out["recipients_ge_20_rows"] = _q(
        "SELECT count(*) FROM (SELECT recipient_id FROM feed_item GROUP BY 1"
        " HAVING count(*) >= 20) t"
    )[0][0]
    out["feed_items"] = _q("SELECT count(*) FROM feed_item")[0][0]
    out["author_refs"] = dict(_q("SELECT kind, count(*) FROM author_ref GROUP BY kind"))
    has_age = _q(
        "SELECT 1 FROM information_schema.columns"
        " WHERE table_name = 'author_ref' AND column_name = 'age_class'"
    )
    out["author_age_class"] = (  # column added by feed/0011 (WP 4b.14)
        dict(_q("SELECT age_class, count(*) FROM author_ref WHERE kind = 'user' GROUP BY 1"))
        if has_age
        else None
    )
    out["synthetic_accounts"] = _q("SELECT count(*) FROM intel_synthetic_account")[0][0]
    out["public_live_posts"] = _q(
        "SELECT count(*) FROM intel_content_ref WHERE audience = 'public'"
        " AND group_id IS NULL AND state = 'live'"
    )[0][0]
    return out


def _arrival() -> dict:
    """New ``feed_item`` rows per recipient per UTC day, and how old a post was when
    its row arrived (``created_at - post_created_at``), p10/p50/p90."""
    rows = _q(
        "SELECT recipient_id, date_trunc('day', created_at AT TIME ZONE 'UTC'), count(*)"
        " FROM feed_item GROUP BY 1, 2"
    )
    out = repetition.arrival_per_day(rows)
    out["days"] = len({r[1] for r in rows})
    out["busiest_day_share"] = None
    if rows:
        by_day = Counter()
        for _r, day, n in rows:
            by_day[day] += n
        out["busiest_day_share"] = round(max(by_day.values()) / sum(by_day.values()), 4)
    lag = [
        float(r[0])
        for r in _q(
            "SELECT extract(epoch FROM (created_at - post_created_at)) / 3600.0 FROM feed_item"
        )
        if r[0] is not None
    ]
    out["arrival_lag_hours"] = repetition.spread(lag)
    return out


def _eligible(viewer_id: str, cfg, now) -> dict:
    """Eligible candidates by kind: connection inventory and pools (when built)."""
    from intel.ranking import home as home_ranker

    viewer = eligibility.Viewer(viewer_id, **ADULT)
    inventory = getattr(home_ranker, "eligible_inventory", None)
    if inventory is not None:
        from intel import discovery

        found = inventory(viewer, cfg, now)
        conn, pools = len(found.connections), len(found.pools)
        # What this variant can serve this viewer: pools only at a share above 0.
        usable = found.pools if pools and discovery.share_for(cfg, conn) > 0 else []
        everything = found.connections + usable
    else:
        candidates, _ = home_ranker.inventory(viewer_id, cfg, now)
        everything = eligibility.filter(viewer, candidates, cfg).kept
        conn, pools = len(everything), 0
    types = _types({c.post_id for c in everything})
    by_author = Counter(c.author_id for c in everything if c.author_id)
    return {
        # The most prolific author's share of what can be served (a cap of 2 per
        # page cannot hold when one author has more than 18 of every 20 items).
        "top_author_share": (max(by_author.values()) / len(everything)) if everything else 0.0,
        "connection_authors": len({c.author_id for c in everything[:conn] if c.author_id}),
        "connections": conn,
        "pools": pools,
        "authors": len({c.author_id for c in everything if c.author_id}),
        "types": len({types.get(c.post_id, c.type) for c in everything}),
    }


def _non_adult_users(author_ids: set[str]) -> int:
    """Recommended authors that are users without a known adult class (rule E9b)."""
    if not author_ids:
        return 0
    adults_or_pages = {
        str(a)
        for (a,) in _q(
            "SELECT account_id FROM author_ref WHERE account_id = ANY(%s::uuid[])"
            " AND (kind = 'page' OR age_class = 'adult')",
            [sorted(author_ids)],
        )
    }
    return len(author_ids - adults_or_pages)


def _types(post_ids: set[str]) -> dict[str, str]:
    if not post_ids:
        return {}
    return {
        str(p): t
        for p, t in _q(
            "SELECT post_id, type FROM intel_content_ref WHERE post_id = ANY(%s::uuid[])",
            [sorted(post_ids)],
        )
    }


class Command(BaseCommand):
    help = "Measure Home repetition (page overlap, recommended share, diversity), read-only."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--variant", default=None, help="home@N (any stored version)")
        parser.add_argument("--users", type=int, default=20)
        parser.add_argument("--opens", type=int, default=4)
        parser.add_argument("--pages", type=int, default=3)
        parser.add_argument("--page-size", type=int, default=20)
        parser.add_argument("--modes", default="for_you,recent")
        parser.add_argument("--min-candidates", type=int, default=60)
        parser.add_argument(
            "--min-connections",
            type=int,
            default=0,
            help="also require this many eligible connection candidates (the share runs)",
        )
        parser.add_argument(
            "--max-connections",
            type=int,
            default=None,
            help="only viewers with fewer eligible connection candidates (thin inventory)",
        )
        parser.add_argument("--clock-offset", default="", help="hours, comma separated")
        parser.add_argument("--crawl-pages", type=int, default=80)
        parser.add_argument("--hot-url", default=None)
        parser.add_argument("--scan", type=int, default=400, help="recipients to consider")
        parser.add_argument(
            "--simulate-display",
            action="store_true",
            help="R3: open A, display, open B at +45 min and +6 h; scenario C (rolled back)",
        )
        parser.add_argument("--display", type=int, default=8, help="page-1 items dwelled 4 s")
        parser.add_argument(
            "--consume",
            type=int,
            default=2,
            help="of the dwelled items, how many are consumed (a like: state consumed)",
        )
        parser.add_argument("--c-visits", type=int, default=5, help="scenario C visits")
        parser.add_argument(
            "--override",
            default=None,
            help="JSON merged over --variant's params (tuning runs; validated, never stored)",
        )

    def handle(self, *args, **opts) -> None:
        url = _hot_url(opts["hot_url"])
        caches = {
            **settings.CACHES,
            "hot": {**settings.CACHES["hot"], "LOCATION": url},
            # The first-page throttles (R3) keep their history here: never the live cache.
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        }
        simulate = opts["simulate_display"]
        started_at = timezone.now()
        result: dict = {}
        with ExitStack() as stack:
            stack.enter_context(override_settings(CACHES=caches))
            from intel import hot

            client = hot.raw_client()
            if client is not None:
                for key in client.scan_iter(match=hot.hot().make_key("*")):
                    client.delete(key)
            override = json.loads(opts["override"]) if opts["override"] else None
            label, patcher = _variant_patch(opts["variant"], override)
            if patcher is not None:
                stack.enter_context(patcher)
            stack.enter_context(mock.patch("feed.ads_client.feed_sponsored", return_value=None))
            try:
                from intel import age

                stack.enter_context(mock.patch.object(age, "capture", return_value=None))
            except ImportError:  # before WP 4b.14
                pass
            if not simulate:
                # Read-only run: the visit rows (R3) are not written at all.
                stack.enter_context(mock.patch("intel.session_ctx._write_rows", return_value=0))
            try:
                with transaction.atomic():
                    if not simulate:
                        with connection.cursor() as cur:
                            cur.execute("SET TRANSACTION READ ONLY")
                    result = self._measure(label, opts)
                    raise _Rollback
            except _Rollback:
                pass
            viewers = result.pop("_viewers", [])
            if simulate:
                result["residual_rows"] = _residual(viewers, started_at)
                if any(result["residual_rows"].values()):
                    raise CommandError(f"rows left after the rollback: {result['residual_rows']}")
            if client is not None:
                for key in client.scan_iter(match=hot.hot().make_key("*")):
                    client.delete(key)
        self.stdout.write(json.dumps(result, indent=1, default=str, sort_keys=True))

    # ------------------------------------------------------------------------------

    def _measure(self, label: str, opts) -> dict:
        from feed import ranking
        from feed import views as fviews
        from rest_framework.test import APIRequestFactory, force_authenticate

        from tara_common.auth import TokenUser

        started = time.monotonic()
        now = timezone.now()
        cfg = config.for_surface("home")
        pools_built = None
        try:
            from intel import discovery

            pools_built = discovery.rebuild(now=now)
        except ImportError:  # before WP 4b.6
            pass
        population = _population()
        arrival = _arrival()

        recipients = [
            str(r[0])
            for r in _q(
                "SELECT recipient_id FROM feed_item GROUP BY recipient_id"
                " HAVING count(*) >= %s ORDER BY md5(recipient_id::text) LIMIT %s",
                [1, opts["scan"]],
            )
        ]
        chosen: list[tuple[str, dict]] = []
        scanned = 0
        counts_all = []
        for viewer_id in recipients:
            if len(chosen) >= opts["users"]:
                break
            scanned += 1
            inv = _eligible(viewer_id, cfg, now)
            counts_all.append(inv["connections"] + inv["pools"])
            if (
                inv["connections"] + inv["pools"] >= opts["min_candidates"]
                and inv["connections"] >= opts["min_connections"]
                and (
                    opts["max_connections"] is None or inv["connections"] < opts["max_connections"]
                )
            ):
                chosen.append((viewer_id, inv))

        rf = APIRequestFactory()
        view = fviews.HomeFeedView.as_view()

        def get(viewer_id: str, params: dict):
            req = rf.get("/api/v1/feed/", params)
            force_authenticate(req, user=TokenUser({"sub": viewer_id, **ADULT}))
            return view(req)

        simulated: dict = {}
        if opts["simulate_display"]:
            captured: list = []
            real_first = ranking.first_page

            def spy(*a, **k):
                page = real_first(*a, **k)
                captured.append(page)
                return page

            def get_at(viewer_id: str, params: dict, at):
                with (
                    mock.patch("feed.views.clock.request_now", return_value=at),
                    mock.patch("feed.views.timezone.now", return_value=at),
                    mock.patch("feed.ranking.first_page", side_effect=spy),
                ):
                    return get(viewer_id, params)

            simulated = self._simulate(chosen, get_at, captured, opts["page_size"], opts)

        modes = [m for m in opts["modes"].split(",") if m]
        size = opts["page_size"]
        per_mode: dict[str, dict] = {}
        offsets = [float(x) for x in opts["clock_offset"].split(",") if x.strip()]
        offset_j: dict[str, list[float]] = {str(o): [] for o in offsets}
        for mode in modes:
            agg = {
                "page1_jaccard": [],
                "pages_jaccard": [],
                "recommended_page1": [],
                "recommended_share_page1": [],
                "outside_connections_page1": [],
                "distinct_authors_page1": [],
                "max_per_author_page": [],
                "longest_format_run_page": [],
                "has_more_false_with_pool_left": 0,
                "rec_by_non_adult_user": 0,
                "page1_under_8_authors_with_8_in_inventory": 0,
                "pages_run_3_with_alternatives": 0,
                "pages_over_author_cap_with_alternatives": 0,
                "top_author_share_of_capped_viewers": [],
                "caught_up_seen": 0,
                "rec_without_reason": 0,
                "crawl_items": [],
                "users": 0,
                "latency_ms": [],
            }
            for viewer_id, inv in chosen:
                agg["users"] += 1
                opens_p1, opens_all = [], []
                first_pages = []
                for _ in range(opts["opens"]):
                    cursor, pages = None, []
                    for _p in range(opts["pages"]):
                        params = {"mode": mode, "limit": size}
                        if cursor:
                            params["cursor"] = cursor
                        t0 = time.perf_counter()
                        resp = get(viewer_id, params)
                        agg["latency_ms"].append((time.perf_counter() - t0) * 1000)
                        if resp.status_code != 200:
                            raise CommandError(f"{mode}: status {resp.status_code}")
                        pages.append(resp.data)
                        cursor = (resp.data.get("page") or {}).get("next_cursor")
                        if not cursor:
                            break
                    first_pages.append(pages)
                    opens_p1.append([i["post_id"] for i in pages[0]["data"]])
                    opens_all.append([i["post_id"] for p in pages for i in p["data"]])
                agg["page1_jaccard"] += repetition.open_overlap(opens_p1)
                agg["pages_jaccard"] += repetition.open_overlap(opens_all)
                pages = first_pages[0]
                types = _types({i["post_id"] for p in pages for i in p["data"]})
                for n, page in enumerate(pages):
                    data = page["data"]
                    authors = [str(i["author_id"]) for i in data]
                    div = repetition.page_diversity(
                        authors, [types.get(i["post_id"], "") for i in data]
                    )
                    agg["max_per_author_page"].append(div["max_per_author"])
                    agg["longest_format_run_page"].append(div["longest_format_run"])
                    if div["longest_format_run"] >= 3 and inv["types"] > 1:
                        agg["pages_run_3_with_alternatives"] += 1
                    # Alternatives: enough servable authors to fill a page at 2 each.
                    if div["max_per_author"] > 2 and 2 * inv["authors"] >= len(data):
                        agg["pages_over_author_cap_with_alternatives"] += 1
                    if div["max_per_author"] > 2:
                        agg["top_author_share_of_capped_viewers"].append(
                            (round(inv["top_author_share"], 3), inv["connection_authors"])
                        )
                    if n == 0:
                        recs = [i for i in data if i.get("source") == DISCOVERY_SOURCE]
                        agg["recommended_page1"].append(len(recs))
                        agg["recommended_share_page1"].append(
                            repetition.share(len(recs), len(data)) or 0.0
                        )
                        agg["rec_without_reason"] += sum(
                            1 for i in recs if not str(i.get("reason", "")).startswith("rec_")
                        )
                        agg["outside_connections_page1"].append(
                            sum(1 for i in data if i.get("reason") not in CONNECTED_REASONS)
                        )
                        agg["distinct_authors_page1"].append(div["distinct_authors"])
                        if div["distinct_authors"] < 8 and inv["authors"] >= 8:
                            agg["page1_under_8_authors_with_8_in_inventory"] += 1
                        agg["rec_by_non_adult_user"] += _non_adult_users(
                            {str(i["author_id"]) for i in recs}
                        )
                if mode == "for_you":
                    agg_crawl = self._crawl(get, viewer_id, size, opts["crawl_pages"])
                    agg["crawl_items"].append(agg_crawl["items"])
                    agg["caught_up_seen"] += int(agg_crawl["caught_up"])
                    if agg_crawl["pool_left"]:
                        agg["has_more_false_with_pool_left"] += 1
            per_mode[mode] = {
                "users": agg["users"],
                "page1_jaccard": repetition.spread(agg["page1_jaccard"]),
                "pages_jaccard": repetition.spread(agg["pages_jaccard"]),
                "recommended_page1": repetition.spread(agg["recommended_page1"]),
                "recommended_page1_total": sum(agg["recommended_page1"]),
                "recommended_share_page1": repetition.spread(agg["recommended_share_page1"]),
                "recommended_share_page1_mean": (
                    sum(agg["recommended_share_page1"]) / len(agg["recommended_share_page1"])
                    if agg["recommended_share_page1"]
                    else None
                ),
                "users_with_recommended_page1": sum(1 for n in agg["recommended_page1"] if n),
                "rec_without_reason": agg["rec_without_reason"],
                "rec_by_non_adult_user": agg["rec_by_non_adult_user"],
                "page1_under_8_authors_with_8_in_inventory": agg[
                    "page1_under_8_authors_with_8_in_inventory"
                ],
                "pages_run_3_with_alternatives": agg["pages_run_3_with_alternatives"],
                "pages_over_author_cap_with_alternatives": agg[
                    "pages_over_author_cap_with_alternatives"
                ],
                "top_author_share_of_capped_viewers": sorted(
                    agg["top_author_share_of_capped_viewers"]
                ),
                "outside_connections_page1": repetition.spread(agg["outside_connections_page1"]),
                "distinct_authors_page1": repetition.spread(agg["distinct_authors_page1"]),
                "max_per_author_page": repetition.spread(agg["max_per_author_page"]),
                "pages_over_author_cap_2": sum(1 for n in agg["max_per_author_page"] if n > 2),
                "longest_format_run_page": repetition.spread(agg["longest_format_run_page"]),
                "pages_with_run_3": sum(1 for n in agg["longest_format_run_page"] if n >= 3),
                "latency_ms": repetition.spread(agg["latency_ms"]),
            }
            if mode == "for_you":
                per_mode[mode].update(
                    {
                        "crawl_items": repetition.spread(agg["crawl_items"]),
                        "caught_up_marked_users": agg["caught_up_seen"],
                        "has_more_false_with_pool_left": agg["has_more_false_with_pool_left"],
                    }
                )

        if offsets:
            for viewer_id, _inv in chosen:
                claims = {"sub": viewer_id, **ADULT}
                base = [
                    str(i.post_id) for i in ranking.first_page(viewer_id, size, now, claims).items
                ]
                for o in offsets:
                    later = ranking.first_page(viewer_id, size, now + timedelta(hours=o), claims)
                    offset_j[str(o)].append(
                        repetition.jaccard(base, [str(i.post_id) for i in later.items])
                    )

        return {
            "_viewers": [v for v, _ in chosen],
            "simulate_display": simulated or None,
            "variant": label,
            "config_active": config.store.resolve("home")[0],
            "measured_at": now.isoformat(),
            "population": population,
            "selection": {
                "rule": f"eligible candidates >= {opts['min_candidates']}, connection"
                f" candidates >= {opts['min_connections']}"
                + (
                    f" and < {opts['max_connections']}"
                    if opts["max_connections"] is not None
                    else ""
                )
                + " (adult claims)",
                "scanned": scanned,
                "chosen": len(chosen),
                "eligible_candidates_scanned": repetition.spread(counts_all),
                "eligible_candidates_chosen": repetition.spread(
                    [inv["connections"] + inv["pools"] for _v, inv in chosen]
                ),
                "pool_candidates_chosen": repetition.spread([inv["pools"] for _v, inv in chosen]),
                "users_with_pool_candidates": sum(1 for _v, inv in chosen if inv["pools"]),
            },
            "pools_rebuilt": pools_built,
            "modes": per_mode,
            "clock_offset_top20_jaccard": {k: repetition.spread(v) for k, v in offset_j.items()},
            "arrival": arrival,
            "visit_gap": "not reachable from feed_db (identity's user_session); "
            "the host wrapper measures it read-only through psql",
            "reels_video_overlap": "post service: measured by the host wrapper (--http-users)",
            "seconds": round(time.monotonic() - started, 1),
        }

    # ---- R3 WP A9: simulated display (07 WP 4b.5 acceptance) --------------------------

    def _simulate(self, chosen, get_at, captured, size: int, opts) -> dict:
        """Open A, display the first ``--display`` page-1 items with 4 s dwell (state
        ``viewed``; the first ``--consume`` of them ``consumed``, as a like would make
        them) and impressions only for the rest (``displayed``), written to the
        throwaway ledger through ``exposure.append_records`` at the simulated clock
        (never through the SQL ingest); a refresh at +60 s with no signals first
        ("fetched is not seen"); then open B at +45 min and at +6 h. Then scenario C
        (06 section 16, early run): ``--c-visits`` visits 45 min apart, 3 pages each,
        impressions for everything served."""
        from intel import exposure

        cfg = config.for_surface("home")
        th_cfg = cfg
        display, dwell_state = opts["display"], exposure.STATE_VIEWED
        consume = min(max(int(opts.get("consume") or 0), 0), display)
        out = {
            "page1_jaccard_45min": [],
            "page1_jaccard_6h": [],
            "dwelled_from_a_in_b_45min": [],
            "dwelled_from_a_in_b_6h": [],
            "consumed_from_a_in_b_45min": [],
            "consumed_from_a_in_b_6h": [],
            "refresh_60s_jaccard": [],
            "pre_score_ratio_45min": [],
            "pre_score_ratio_6h": [],
            "first_page_ms": [],
            "first_page_queries": [],
            "first_page_writes": [],
            "kinds": Counter(),
            "c_repeat_first_pages": [],
            "c_repeat_all_pages": [],
        }
        base = timezone.now().replace(microsecond=0)

        def first(viewer_id, at, entry):
            t0 = time.perf_counter()
            with CaptureQueriesContext(connection) as q:
                resp = get_at(viewer_id, {"mode": "for_you", "limit": size, "entry": entry}, at)
            out["first_page_ms"].append((time.perf_counter() - t0) * 1000)
            sql = [x["sql"].lstrip().upper() for x in q.captured_queries]
            sql = [x for x in sql if not x.startswith(("SAVEPOINT", "RELEASE SAVEPOINT"))]
            writes = [x for x in sql if x.startswith(("INSERT", "UPDATE", "DELETE"))]
            out["first_page_queries"].append(len(sql) - len(writes))
            out["first_page_writes"].append(len(writes))
            if resp.status_code != 200:
                raise CommandError(f"for_you first page: status {resp.status_code}")
            visit = (resp.data.get("meta") or {}).get("visit") or {}
            out["kinds"][visit.get("kind")] += 1
            page = captured[-1] if captured else None
            ids = [i["post_id"] for i in resp.data["data"]]
            return resp, ids, _pre_scores(page, ids)

        def show(viewer_id, at, ids, n_dwell, n_consume=0):
            minute = int((at + timedelta(minutes=1)).timestamp() // 60)

            def state(k):
                if k < n_consume:
                    return exposure.STATE_CONSUMED  # a like / long read (06 section 5.1)
                return dwell_state if k < n_dwell else exposure.STATE_DISPLAYED

            records = [exposure.Record(p, state(k), minute) for k, p in enumerate(ids)]
            if records and not exposure.append_records(viewer_id, records, th_cfg):
                raise CommandError("the throwaway ledger refused a write")

        for viewer_id, _inv in chosen:
            t_a = base
            _r, a_ids, a_pre = first(viewer_id, t_a, "load")
            # Fetched is not seen: no signal, pools frozen, a refresh 60 s later.
            _r, r_ids, _ = first(viewer_id, t_a + timedelta(seconds=60), "pull")
            out["refresh_60s_jaccard"].append(repetition.jaccard(a_ids, r_ids))
            show(viewer_id, t_a + timedelta(seconds=90), a_ids, display, consume)
            consumed = set(a_ids[:consume])
            dwelled = set(a_ids[consume:display])
            for label, gap in (("45min", timedelta(minutes=45)), ("6h", timedelta(hours=6))):
                _r, b_ids, b_pre = first(viewer_id, t_a + gap, "load")
                out[f"page1_jaccard_{label}"].append(repetition.jaccard(a_ids, b_ids))
                out[f"dwelled_from_a_in_b_{label}"].append(len(dwelled & set(b_ids)))
                out[f"consumed_from_a_in_b_{label}"].append(len(consumed & set(b_ids)))
                if a_pre and b_pre:
                    a_mean = sum(a_pre) / len(a_pre)
                    b_mean = sum(b_pre) / len(b_pre)
                    if a_mean > 0:
                        out[f"pre_score_ratio_{label}"].append(b_mean / a_mean)

        # Scenario C (heavy user), a fresh clock so A/B's ledger does not count.
        c_base = base + timedelta(days=2)
        for viewer_id, _inv in chosen:
            shown: set[str] = set()
            for v in range(opts["c_visits"]):
                at = c_base + timedelta(minutes=45 * v)
                resp, ids, _ = first(viewer_id, at, "load")
                pages = [ids]
                cursor = (resp.data.get("page") or {}).get("next_cursor")
                for _p in range(2):
                    if not cursor:
                        break
                    nxt = get_at(
                        viewer_id, {"mode": "for_you", "limit": size, "cursor": cursor}, at
                    )
                    pages.append([i["post_id"] for i in nxt.data["data"]])
                    cursor = (nxt.data.get("page") or {}).get("next_cursor")
                if v:
                    out["c_repeat_first_pages"].append(repetition.repeat_rate(pages[0], shown))
                    out["c_repeat_all_pages"].append(
                        repetition.repeat_rate([p for page in pages for p in page], shown)
                    )
                served = [p for page in pages for p in page]
                show(viewer_id, at, served, 0)
                shown |= set(served)

        def mean(values):
            return sum(values) / len(values) if values else None

        return {
            "users": len(chosen),
            "display": f"first {display} page-1 items dwelled: {consume} consumed, the other "
            f"{display - consume} 4 s (viewed); the rest impressions",
            "page1_jaccard_45min": repetition.spread(out["page1_jaccard_45min"]),
            "page1_jaccard_6h": repetition.spread(out["page1_jaccard_6h"]),
            "dwelled_from_a_in_b_45min": repetition.spread(out["dwelled_from_a_in_b_45min"]),
            "dwelled_from_a_in_b_6h": repetition.spread(out["dwelled_from_a_in_b_6h"]),
            "consumed_from_a_in_b_45min": repetition.spread(out["consumed_from_a_in_b_45min"]),
            "consumed_from_a_in_b_6h": repetition.spread(out["consumed_from_a_in_b_6h"]),
            "consumed_from_a_in_b_max": max(
                out["consumed_from_a_in_b_45min"] + out["consumed_from_a_in_b_6h"], default=None
            ),
            "refresh_60s_jaccard": repetition.spread(out["refresh_60s_jaccard"]),
            "pre_score_ratio_45min": repetition.spread(out["pre_score_ratio_45min"]),
            "pre_score_ratio_6h": repetition.spread(out["pre_score_ratio_6h"]),
            "pre_score_ratio_45min_mean": mean(out["pre_score_ratio_45min"]),
            "pre_score_ratio_6h_mean": mean(out["pre_score_ratio_6h"]),
            "first_page_ms": {
                **repetition.spread(out["first_page_ms"]),
                "p95": repetition.percentile(out["first_page_ms"], 0.95),
            },
            "first_page_queries": {
                **repetition.spread(out["first_page_queries"]),
                "p95": repetition.percentile(out["first_page_queries"], 0.95),
            },
            "first_page_writes": dict(Counter(out["first_page_writes"])),
            "visit_kinds": dict(out["kinds"]),
            "scenario_c": {
                "visits": opts["c_visits"],
                "repeat_rate_first_pages": repetition.spread(out["c_repeat_first_pages"]),
                "repeat_rate_all_pages": repetition.spread(out["c_repeat_all_pages"]),
                "repeat_rate_first_pages_mean": mean(out["c_repeat_first_pages"]),
                "repeat_rate_all_pages_mean": mean(out["c_repeat_all_pages"]),
            },
        }

    def _crawl(self, get, viewer_id: str, size: int, limit: int) -> dict:
        """Follow ``for_you`` to its end: items served, whether a ``caught_up`` marker
        appeared, and whether the feed ended while eligible pool items were unserved."""
        cursor, served, caught = None, set(), False
        more = True
        for _ in range(limit):
            params = {"mode": "for_you", "limit": size}
            if cursor:
                params["cursor"] = cursor
            resp = get(viewer_id, params)
            data = resp.data
            served |= {i["post_id"] for i in data["data"]}
            if (data.get("meta") or {}).get("caught_up_index") is not None:
                caught = True
            cursor = (data.get("page") or {}).get("next_cursor")
            if not cursor:
                more = False
                break
        pool_left = False
        if not more:
            try:
                from intel import discovery
            except ImportError:
                discovery = None
            if discovery is not None:
                cfg = config.for_surface("home")
                left = discovery.viewer_pool_ids(
                    eligibility.Viewer(viewer_id, **ADULT), cfg, timezone.now()
                )
                pool_left = bool(set(left) - served) and discovery.continues(cfg)
        return {"items": len(served), "caught_up": caught, "pool_left": pool_left}


def _pre_scores(page, ids: list[str]) -> list[float]:
    """The pre-multiplier scores of a served page's items (the ranking's own values;
    ``exposure.pre`` when the version applies the multiplier)."""
    ranking = getattr(page, "ranking", None)
    if ranking is None:
        return []
    stats = getattr(ranking, "exposure", None)
    values = {s.feats.post_id: s.value for s in ranking.items}
    if stats is not None:
        values.update(stats.pre)
    return [values[p] for p in ids if p in values]


def _residual(viewers: list[str], since) -> dict:
    """Rows of the chosen viewers written since the run started, after the rollback:
    visit rows and signal rows (both must be 0: synthetic display never stays)."""
    if not viewers:
        return {"intel_feed_session": 0, "intel_signal_event": 0}
    return {
        "intel_feed_session": _q(
            "SELECT count(*) FROM intel_feed_session WHERE account_id = ANY(%s::uuid[])"
            " AND started_at >= %s",
            [viewers, since],
        )[0][0],
        "intel_signal_event": _q(
            "SELECT count(*) FROM intel_signal_event WHERE account_id = ANY(%s::uuid[])"
            " AND received_at >= %s",
            [viewers, since],
        )[0][0],
    }


def stable_order(ids: list[str]) -> list[str]:
    """The order the selection query uses (md5 of the id), for tests."""
    return sorted(ids, key=lambda i: hashlib.md5(i.encode(), usedforsecurity=False).hexdigest())
