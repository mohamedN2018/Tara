#!/usr/bin/env python3
"""Tara Intelligence WP 3.6: hydration drops measured on the server.

For every seeded viewer (``.seed-state/manifest.json``):

1. **Served Home.** Ask feed for the items it serves on each Home mode and
   hydrate them through post's ``/posts/batch/`` with the ``surface`` / ``src``
   hints feed gave. This also proves every Home mode still answers.
2. **Intel candidates.** Ask feed's retrieval + eligibility pipeline
   (``manage.py intel_candidates`` in the feed container, with the viewer's own
   age claims from its access token) for its eligible candidates on every
   surface (home, groups, reels, video), and hydrate them as that viewer
   through ``/posts/batch/`` (``/reels/batch/`` for the reels surface) with
   ``src`` = the candidate source.

Then read post's own counter ``post_batch_dropped_total{caller,surface,src}``
before and after. Client flags are never used: the numbers come from post's
``/metrics``.

Fails (exit 1) if any non-connection source (``follow_pull``, ``groups``,
``reels``, ``video``, ``discovery``, ``trending``, ``new_creators``) dropped
an id: those items never went through the fan-out audience check, only
feed's fail-closed eligibility, so post refusing one means a leak upstream.
Connection sources may drop a few (an audience narrowed after fan-out).

Needs the running dev stack. Standard library only. Read-only: it signs in
and reads; it writes nothing but ranking sessions in ``redis-hot``.

    python scripts/integration/intel_privacy.py [--limit N] [--served-only]
    TARA_API=http://127.0.0.1:8080/api/v1 TARA_POST_METRICS=http://127.0.0.1:8004/metrics
    TARA_FEED_CONTAINER=tara-feed-1

The counter is process-wide, so traffic from other clients during the run is
included in the deltas; run it on a quiet stack for an exact reading. The
per-id check of step 2 compares the response itself, so it is exact.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

API = os.getenv("TARA_API", "http://127.0.0.1:8080/api/v1")
POST_METRICS = os.getenv("TARA_POST_METRICS", "http://127.0.0.1:8004/metrics")
FEED_CONTAINER = os.getenv("TARA_FEED_CONTAINER", "tara-feed-1")
# The seed's documented default (scripts/seed/README.md); override with the env.
SEED_PASSWORD = os.getenv("TARA_SEED_PASSWORD", "Seed-Tara-2026!")
MANIFEST = Path(__file__).resolve().parents[2] / ".seed-state" / "manifest.json"
MODES = ("recent", "for_you", "following", "favorites")
PAGES_PER_MODE = 2
BATCH_LIMIT = 50
DISCOVERY_SOURCES = {"discovery", "trending", "new_creators"}
# Decided by eligibility alone (no fan-out audience check): post must return each.
PULL_SOURCES = {"follow_pull", "groups", "reels", "video"}
INTEL_SURFACES = ("home", "groups", "reels", "video")
ADULT_BANDS = {"18-24", "25-34", "35-44", "45+"}
_SAMPLE = re.compile(r"^post_batch_dropped_total\{([^}]*)\}\s+([0-9.eE+-]+)$")
_LABEL = re.compile(r'(\w+)="([^"]*)"')


def call(method: str, path: str, token: str | None = None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    url = path if path.startswith("http") else API + path
    request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 - http(s) API base from the env
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            status, payload = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, payload = exc.code, exc.read()
    try:
        return status, json.loads(payload)
    except ValueError:
        return status, payload


def dropped() -> Counter:
    """post's counter now, as {(caller, surface, src): value}."""
    with urllib.request.urlopen(POST_METRICS, timeout=30) as response:  # noqa: S310
        text = response.read().decode()
    out: Counter = Counter()
    for line in text.splitlines():
        m = _SAMPLE.match(line.strip())
        if m:
            labels = dict(_LABEL.findall(m.group(1)))
            out[(labels.get("caller"), labels.get("surface"), labels.get("src"))] += float(
                m.group(2)
            )
    return out


def viewers(limit: int | None) -> list[str]:
    accounts = json.loads(MANIFEST.read_text(encoding="utf-8"))["accounts"]
    emails = [a["email"] for _, a in sorted(accounts.items()) if a.get("email")]
    return emails[:limit] if limit else emails


def claims(token: str) -> dict:
    """The access token's own claims (read, not verified: post verifies the token)."""
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def served(token: str) -> list[tuple[str, str]]:
    """(post_id, source) for every Home item the viewer is served."""
    out: list[tuple[str, str]] = []
    for mode in MODES:
        cursor = None
        for _ in range(PAGES_PER_MODE):
            query = f"/feed/?mode={mode}" + (f"&cursor={cursor}" if cursor else "")
            status, body = call("GET", query, token)
            if status != 200 or not isinstance(body, dict):
                raise SystemExit(f"feed mode {mode} answered HTTP {status}")
            for item in body.get("data") or []:
                out.append((item["post_id"], item.get("source") or item.get("reason") or ""))
            page = body.get("page") or {}
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                break
    return out


def intel_candidates(keys: list[str], surface: str) -> dict[str, list[tuple[str, str]]]:
    """``{viewer id: [(post_id, source)]}`` of eligible candidates, one feed call per
    surface. ``keys`` are ``<uuid>`` or ``<uuid>:adult``."""
    if not keys:
        return {}
    argv = ["docker", "exec", FEED_CONTAINER, "python", "manage.py", "intel_candidates"]
    out = subprocess.run(  # noqa: S603 - fixed argv; ids come from the tokens
        [*argv, "--surface", surface, *keys],
        capture_output=True,
        text=True,
        check=True,
        timeout=1800,
    ).stdout
    result: dict[str, list[tuple[str, str]]] = {}
    for line in out.splitlines():
        if line.startswith("{"):
            row = json.loads(line)
            result[row["viewer"]] = [(i["post_id"], i["source"]) for i in row["items"]]
    return result


def hydrate(token: str, items: list[tuple[str, str]], surface: str = "home") -> list[str]:
    """Hydrate ``items`` as the viewer; returns the ids post did not return."""
    endpoint = "/reels/batch/" if surface == "reels" else "/posts/batch/"
    missing: list[str] = []
    for i in range(0, len(items), BATCH_LIMIT):
        chunk = items[i : i + BATCH_LIMIT]
        ids = [p for p, _ in chunk]
        status, body = call(
            "POST", endpoint, token, {"ids": ids, "surface": surface, "src": [s for _, s in chunk]}
        )
        if status != 200:
            raise SystemExit(f"{endpoint} answered {status}: {body}")
        got = {str(p.get("post_id") or p.get("id")) for p in body["data"]}
        missing += [p for p in ids if p not in got]
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None, help="first N seed viewers only")
    parser.add_argument(
        "--served-only", action="store_true", help="skip the intel candidates (no docker)"
    )
    args = parser.parse_args()

    before = dropped()
    asked = returned = 0
    by_src: Counter = Counter()
    tokens: dict[str, str] = {}  # "<uuid>" or "<uuid>:adult" -> access token
    for email in viewers(args.limit):
        status, body = call(
            "POST", "/auth/login/", body={"email": email, "password": SEED_PASSWORD}
        )
        if status != 200:
            print(f"  sign-in failed for a seed viewer: HTTP {status}", file=sys.stderr)
            continue
        token = body["data"]["access_token"]
        c = claims(token)
        adult = c.get("is_minor") is False and c.get("age_band") in ADULT_BANDS
        tokens[str(c["sub"]) + (":adult" if adult else "")] = token
        items = served(token)
        by_src.update(s for _, s in items)
        asked += len(items)
        returned += len(items) - len(hydrate(token, items))

    intel_asked: Counter = Counter()
    intel_missing: Counter = Counter()
    leaked: list[tuple[str, str, str]] = []
    if not args.served_only:
        for surface in INTEL_SURFACES:
            found = intel_candidates(sorted(tokens), surface)
            for key, token in tokens.items():
                items = found.get(key.partition(":")[0], [])
                intel_asked.update((surface, s) for _, s in items)
                source_of = dict(items)
                for post_id in hydrate(token, items, surface):
                    src = source_of[post_id]
                    intel_missing[(surface, src)] += 1
                    if src in PULL_SOURCES | DISCOVERY_SOURCES:
                        leaked.append((surface, src, post_id))
    after = dropped()

    delta = {k: after[k] - before.get(k, 0.0) for k in after if after[k] - before.get(k, 0.0)}
    adults = sum(1 for k in tokens if k.endswith(":adult"))
    print(f"viewers signed in: {len(tokens)} ({adults} adult, {len(tokens) - adults} limited)")
    print(f"served Home ids requested: {asked}, returned: {returned}, missing: {asked - returned}")
    print(f"served sources: {dict(sorted(by_src.items()))}")
    if intel_asked:
        print("intel candidates hydrated (surface, src): requested / missing")
        for key in sorted(intel_asked):
            print(f"  {key}: {intel_asked[key]} / {intel_missing.get(key, 0)}")
    print("post_batch_dropped_total deltas (caller, surface, src):")
    for key in sorted(delta, key=lambda k: tuple(x or "" for x in k)):
        print(f"  {key}: {delta[key]:g}")
    if not tokens:
        print("FAIL: no seed viewer could sign in")
        return 1
    leaks = {k: v for k, v in delta.items() if k[2] in DISCOVERY_SOURCES | PULL_SOURCES}
    if leaks or leaked:
        print(f"FAIL: non-connection sources dropped ids: {leaks}")
        for surface, src, post_id in leaked[:20]:
            print(f"  {surface}/{src}: {post_id}")
        return 1
    print("OK: non-connection sources (pull and discovery) dropped 0 ids")
    return 0


if __name__ == "__main__":
    sys.exit(main())
