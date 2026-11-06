"""``intel_creator_quality``, rebuilt nightly (04 WP 6.3, 03 section 2.5).

Per author with a live post in ``creator_quality.window_d`` days, from ``feed_db`` only:

- ``followers``: active ``follow_edge`` rows; ``account_age_days``: ``author_ref.registered_at``;
- ``posts_30d``; ``reach_30d``: fan-out recipients of those posts (the honest denominator
  before impressions are aggregated);
- ``hide_rate``: hides of those posts over reach; ``report_rate_90d``: distinct
  reporters (``post_report`` signal rows, ids never copied) over reach; ``removal_rate_90d``:
  removed posts over posts; every rate smoothed with the Beta prior
  ``(prior_events, prior_reach)``;
- ``comment_depth``: mean ``log1p(distinct commenters)``; ``originality``: the share of
  posts that are not reshares;
- ``quality = sigmoid(w_depth*depth + w_originality*originality - w_hide*hide_rate
  - w_report*report_rate - w_removal*removal_rate)``: a score, not a probability;
- ``is_new``: registered within ``new_account_days``.

Synthetic and test actors are left out of the rates (their reports and hides) unless
``INTEL_SYNTHETIC_IN_RANKING`` (03 section 2.5). Every weight is in the config.
"""

from __future__ import annotations

import math
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

_SQL = """
WITH posts AS (
    SELECT post_id, author_id, shared_post_id, moderation_state
    FROM intel_content_ref
    WHERE author_id IS NOT NULL AND created_at >= %(since)s AND state IN ('live', 'deleted')),
authors AS (SELECT DISTINCT author_id FROM posts),
reach AS (
    SELECT p.author_id, count(*) AS n FROM feed_item f JOIN posts p ON p.post_id = f.post_id
    GROUP BY p.author_id),
hides AS (
    SELECT p.author_id, count(*) AS n FROM post_hide h JOIN posts p ON p.post_id = h.post_id
    WHERE (%(synthetic)s OR h.account_id NOT IN (SELECT account_id FROM intel_synthetic_account))
    GROUP BY p.author_id),
reports AS (
    SELECT e.author_id, count(DISTINCT e.account_id) AS n FROM intel_signal_event e
    WHERE e.event_type = 'post_report' AND e.received_at >= %(since_reports)s
      AND e.author_id IN (SELECT author_id FROM authors)
      AND (%(synthetic)s OR e.data_origin = 'real')
    GROUP BY e.author_id),
depth AS (
    SELECT p.author_id, avg(ln(1 + coalesce(k.n, 0))) AS d
    FROM posts p LEFT JOIN (
        SELECT post_id, count(DISTINCT author_id) AS n FROM comment_state
        WHERE active AND post_id IN (SELECT post_id FROM posts) GROUP BY post_id) k
      ON k.post_id = p.post_id
    GROUP BY p.author_id),
followers AS (
    SELECT target_id AS author_id, count(*) AS n FROM follow_edge
    WHERE active AND target_id IN (SELECT author_id FROM authors) GROUP BY target_id)
SELECT a.author_id,
       coalesce(fo.n, 0),
       r.registered_at,
       (SELECT count(*) FROM posts p WHERE p.author_id = a.author_id),
       coalesce(re.n, 0),
       coalesce(h.n, 0),
       coalesce(rp.n, 0),
       (SELECT count(*) FROM posts p WHERE p.author_id = a.author_id
          AND p.moderation_state = 'removed'),
       coalesce(d.d, 0),
       (SELECT count(*) FROM posts p WHERE p.author_id = a.author_id AND p.shared_post_id IS NULL)
FROM authors a
LEFT JOIN followers fo ON fo.author_id = a.author_id
LEFT JOIN author_ref r ON r.account_id = a.author_id
LEFT JOIN reach re ON re.author_id = a.author_id
LEFT JOIN hides h ON h.author_id = a.author_id
LEFT JOIN reports rp ON rp.author_id = a.author_id
LEFT JOIN depth d ON d.author_id = a.author_id
"""

_UPSERT = """
INSERT INTO intel_creator_quality (author_id, followers, account_age_days, posts_30d,
    reach_30d, hide_rate, report_rate_90d, removal_rate_90d, completion, comment_depth,
    originality, quality, is_new, computed_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s)
ON CONFLICT (author_id) DO UPDATE SET followers = EXCLUDED.followers,
    account_age_days = EXCLUDED.account_age_days, posts_30d = EXCLUDED.posts_30d,
    reach_30d = EXCLUDED.reach_30d, hide_rate = EXCLUDED.hide_rate,
    report_rate_90d = EXCLUDED.report_rate_90d, removal_rate_90d = EXCLUDED.removal_rate_90d,
    comment_depth = EXCLUDED.comment_depth, originality = EXCLUDED.originality,
    quality = EXCLUDED.quality, is_new = EXCLUDED.is_new, computed_at = EXCLUDED.computed_at
"""


def _rate(events: float, total: float, prior_events: float, prior_total: float) -> float:
    return (max(events, 0.0) + prior_events) / (max(total, events, 0.0) + prior_total)


def rebuild(now=None, cfg=None) -> dict:
    from . import config

    now = now or timezone.now()
    b = (cfg or config.for_surface("home")).section("creator_quality")
    params = {
        "since": now - timedelta(days=b["window_d"]),
        "since_reports": now - timedelta(days=b["report_window_d"]),
        "synthetic": bool(settings.INTEL_SYNTHETIC_IN_RANKING),
    }
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(_SQL, params)
        rows = cur.fetchall()
        for (
            author,
            followers,
            registered,
            posts,
            reach,
            hides,
            reporters,
            removed,
            depth,
            orig,
        ) in rows:
            hide_rate = _rate(hides, reach, b["prior_events"], b["prior_reach"])
            report_rate = _rate(reporters, reach, b["prior_events"], b["prior_reach"])
            removal_rate = _rate(removed, posts, b["prior_events"], b["prior_posts"])
            originality = orig / posts if posts else 0.0
            x = (
                b["w_depth"] * float(depth)
                + b["w_originality"] * originality
                - b["w_hide"] * hide_rate
                - b["w_report"] * report_rate
                - b["w_removal"] * removal_rate
            )
            quality = 1.0 / (1.0 + math.exp(-x))
            age = (now - registered).days if registered else None
            cur.execute(
                _UPSERT,
                [
                    author,
                    followers,
                    age,
                    posts,
                    reach,
                    hide_rate,
                    report_rate,
                    removal_rate,
                    float(depth),
                    originality,
                    quality,
                    age is not None and age <= b["new_account_days"],
                    now,
                ],
            )
    return {"authors": len(rows)}
