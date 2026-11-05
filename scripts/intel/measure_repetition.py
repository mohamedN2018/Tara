#!/usr/bin/env python3
"""Host wrapper of the repetition harness (Tara Intelligence 07 WP 4b.1).

Runs ``manage.py intel_measure_repetition`` (read-only, sessions in a throwaway
redis-hot database) inside the dev stack and adds the two measurements that do not
live in feed_db:

- **visit gap** (``--visit-gap``): gaps between successive ``user_session`` rows per
  account, from identity's database, through ``psql`` in the postgres container in a
  read-only transaction (``SET TRANSACTION READ ONLY``);
- **reels / video overlap** (``--http-users N``): N seeded accounts log in through
  the gateway and open the reels ``for_you`` tab and ``/posts/?type=video`` twice;
  Jaccard of the two opens and the page sizes. Credentials: the seed accounts'
  e-mails from ``.seed-state/manifest.json`` and ``TARA_SEED_PASSWORD`` (else the
  seed script's documented dev default). They are never printed. Logging in writes
  identity sessions: this part is opt-in and off by default.

The output names no account: counts, ratios and distributions only.

    python scripts/intel/measure_repetition.py -- --variant home@3 --users 20
    python scripts/intel/measure_repetition.py --mount-source --visit-gap -- --users 20
    python scripts/intel/measure_repetition.py --http-users 5 --out runs/baseline.json

``--mount-source`` runs the command from the working tree (``services/feed`` mounted
over the image's code, as the phase-4 probe did) instead of the running container.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "infra/compose/docker-compose.yml")]
COMPOSE += ["--env-file", str(ROOT / ".env")]
GATEWAY = os.getenv("TARA_GATEWAY", "http://127.0.0.1:8080/api/v1")

_GAP_SQL = """
BEGIN;
SET TRANSACTION READ ONLY;
WITH s AS (
  SELECT account_id, created_at,
         lag(created_at) OVER (PARTITION BY account_id ORDER BY created_at) AS prev
  FROM user_session)
SELECT count(*) AS gaps,
       count(DISTINCT account_id) AS accounts,
       percentile_cont(0.1) WITHIN GROUP (ORDER BY extract(epoch FROM created_at - prev)),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM created_at - prev)),
       percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM created_at - prev))
FROM s WHERE prev IS NOT NULL;
SELECT count(*) FROM user_session;
ROLLBACK;
"""


def _env_file() -> str:
    """``.env`` without inline comments (``docker run --env-file`` keeps them)."""
    lines = []
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = re.sub(r"\s+#.*$", "", raw)
        if re.match(r"^[A-Z0-9_]+=", line):
            lines.append(line)
    fd, path = tempfile.mkstemp(prefix="tara-harness-", suffix=".env")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def run_command(args: list[str], mount: bool) -> dict:
    if mount:
        env_path = _env_file()
        try:
            cmd = [
                "docker", "run", "--rm", "--network", "tara_default", "--env-file", env_path,
                "-e", "POSTGRES_HOST=postgres", "-e", "REDIS_URL=redis://redis:6379/14",
                "-e", "REDIS_HOT_URL=redis://redis-hot:6379/0", "-e", "RABBITMQ_URL=",
                "-e", "INTEL_ACCEPT_SYNTHETIC=true", "-e", "INTEL_SYNTHETIC_IN_RANKING=true",
                "-v", f"{ROOT / 'services/feed'}:/app", "--entrypoint", "python", "tara/feed:dev",
                "manage.py", "intel_measure_repetition", *args,
            ]  # fmt: skip
            out = subprocess.run(  # noqa: S603 - fixed argv, no shell
                cmd, check=True, capture_output=True, text=True,
                env={**os.environ, "MSYS_NO_PATHCONV": "1"},
            )  # fmt: skip
        finally:
            os.unlink(env_path)
    else:
        cmd = [*COMPOSE, "exec", "-T", "feed", "python", "manage.py", "intel_measure_repetition"]
        out = subprocess.run([*cmd, *args], check=True, capture_output=True, text=True)  # noqa: S603
    text = out.stdout
    return json.loads(text[text.index("{") :])


def visit_gap() -> dict:
    cmd = [
        "docker", "exec", "-i", "tara-postgres-1", "sh", "-c",
        'psql -U "$POSTGRES_USER" -d "$IDENTITY_DB_NAME" -At -F "|"',
    ]  # fmt: skip
    out = subprocess.run(cmd, input=_GAP_SQL, capture_output=True, text=True, check=True)  # noqa: S603
    rows = [r for r in out.stdout.splitlines() if "|" in r or r.strip().isdigit()]
    gaps = rows[0].split("|") if rows else []
    if len(gaps) < 5:
        return {"error": "user_session not readable"}

    def num(v):
        return round(float(v), 3) if v not in ("", None) else None

    return {
        "source": "identity.user_session, read-only transaction",
        "sessions": int(rows[1]) if len(rows) > 1 else None,
        "gaps": int(gaps[0]),
        "accounts": int(gaps[1]),
        "gap_seconds": {"p10": num(gaps[2]), "p50": num(gaps[3]), "p90": num(gaps[4])},
    }


def _seed_password() -> str:
    pw = os.getenv("TARA_SEED_PASSWORD")
    if pw:
        return pw
    text = (ROOT / "scripts/seed/seed_dataset.py").read_text(encoding="utf-8")
    m = re.search(r'TARA_SEED_PASSWORD",\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("set TARA_SEED_PASSWORD")
    return m.group(1)


def _req(method: str, path: str, token=None, body=None, params=None):
    url = GATEWAY + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)  # noqa: S310 - http gateway
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def _jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 1.0


def http_overlap(n: int) -> dict:
    manifest = json.loads((ROOT / ".seed-state/manifest.json").read_text(encoding="utf-8"))
    emails = sorted(a["email"] for a in manifest["accounts"].values())[:n]
    password = _seed_password()
    reels_j, video_j, video_sizes, reels_sizes, failures = [], [], [], [], 0
    for email in emails:
        st, d = _req("POST", "/auth/login/", body={"email": email, "password": password})
        if st != 200:
            failures += 1
            continue
        tok = d["data"]["access_token"]
        opens_r, opens_v = [], []
        for _ in range(2):
            _s, r = _req("GET", "/reels/", tok, params={"tab": "for_you"})
            opens_r.append([i.get("id") or i.get("post_id") for i in r.get("data", [])])
            _s, v = _req("GET", "/posts/", tok, params={"type": "video"})
            opens_v.append([i.get("id") for i in v.get("data", [])])
        reels_j.append(_jaccard(*opens_r))
        video_j.append(_jaccard(*opens_v))
        reels_sizes.append(len(opens_r[0]))
        video_sizes.append(len(opens_v[0]))
    return {
        "users": len(reels_j),
        "login_failures": failures,
        "reels_for_you_jaccard": reels_j and sorted(reels_j),
        "reels_page_sizes": reels_sizes,
        "video_jaccard": video_j and sorted(video_j),
        "video_page_sizes": video_sizes,
    }


def warm_ages(n: int) -> dict:
    """Dev warm-up (07 WP 4b.14): seed accounts log in and open their feed once, so
    feed captures each one's age class from its own token (the real capture path).
    Returns counts only; the classes themselves are then read by query."""
    manifest = json.loads((ROOT / ".seed-state/manifest.json").read_text(encoding="utf-8"))
    emails = sorted(a["email"] for a in manifest["accounts"].values())[:n]
    password = _seed_password()
    done = failures = 0
    for email in emails:
        st, d = _req("POST", "/auth/login/", body={"email": email, "password": password})
        if st != 200:
            failures += 1
            continue
        st, _ = _req("GET", "/feed/", d["data"]["access_token"], params={"limit": 1})
        done += st == 200
        failures += st != 200
    return {"accounts": len(emails), "feed_requests_ok": done, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mount-source", action="store_true")
    parser.add_argument("--visit-gap", action="store_true")
    parser.add_argument("--http-users", type=int, default=0)
    parser.add_argument("--warm-ages", type=int, default=0, help="seed accounts to warm (dev)")
    parser.add_argument("--out", default=None)
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    rest = [a for a in ns.rest if a != "--"]
    warmed = warm_ages(ns.warm_ages) if ns.warm_ages else None
    result = run_command(rest, ns.mount_source)
    if warmed:
        result["age_warm_up"] = warmed
    if ns.visit_gap:
        result["visit_gap"] = visit_gap()
    if ns.http_users:
        result["reels_video_overlap"] = http_overlap(ns.http_users)
    text = json.dumps(result, indent=1, sort_keys=True, default=str)
    if ns.out:
        Path(ns.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
