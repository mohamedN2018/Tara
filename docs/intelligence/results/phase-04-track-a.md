# Phase 4 results, track A: ranking core (WP 4.1 to 4.5, 4.10)

Date: 2026-11-05. Dev stack as in [phase-03.md](phase-03.md), seeded dataset in
`.seed-state/`, nothing wiped. Track B (WP 4.6 to 4.9, 4.11) has its own notes in
[phase-04-track-b.md](phase-04-track-b.md). Every count below was taken by a query or a
run at the time shown, never compared with a fixed row count (04, section 0).

## Status per work package

| WP | Status | Where |
|---|---|---|
| 4.1 Config store | Done | `intel/config/{schema,store,__init__}.py`, `defaults/home.json` (`home@1`), `defaults/home.v2.json`, models `RankingConfig` / `RankingConfigChange` (`intel/models.py`), migration `intel/0004_ranking_config` (tables, partial unique index, immutability trigger, version-1 load), `manage.py intel_config`, event `intel.config.changed` (schema in `libs/tara_events`), admin handler `audit_intel_config_changed` |
| 4.2 Features and predictions | Done | `intel/ranking/features.py` (10 batched queries), `intel/predictions/{base,rules,__init__}.py` (`RulePredictor`, outputs `score_*`, `calibrated=False`) |
| 4.3 Home ranker | Done | `intel/ranking/{home,scorer,explain}.py`; `feed/ranking.py::rank_items` and `first_page` always delegate to `intel.ranking.home.rank` |
| 4.4 Integrity | Done | `intel/integrity.py`, lexicons `intel/topics/lexicons/bait_{ar,en}.txt`, gold set `intel/tests/fixtures/bait_gold.jsonl`, `ContentRef.dup_of` (`intel/0005`), `ReactionState.suspect` and `AuthorRef.registered_at` (`feed/0010`), `account.registered` consumer |
| 4.5 Diversity re-ranker | Done | `intel/ranking/diversity.py` |
| 4.10 Ranking session v2 | Done | `intel/ranking/session.py`, `intel/eligibility.py::recheck`, `feed/ranking.py` (`first_page`, `next_page`) |

## Acceptance evidence

### WP 4.1

- **Invalid params are rejected:** `test_config_schema.py` (23 tests: unknown section and
  key, weights outside [-10, 10], NaN, strings, booleans, half-life <= 0, ratios that do
  not sum to 1, multipliers outside (0, 1], bad Beta priors, unknown reason or source,
  wrong surface). `store.create` and `store.activate` both validate; an invalid version
  is never stored (`test_invalid_params_are_never_stored`).
- **An active version is immutable:** the model's `save()` refuses a params change, and
  the trigger `intel_rcfg_immutable` rejects a raw SQL `UPDATE ... SET params` and any
  `DELETE` of a non-draft row (`test_an_active_version_is_immutable_in_the_model_and_in_the_database`).
  The partial unique index allows one active version per surface.
- **Every change is audited:** create, activate and rollback write an
  `intel_ranking_config_change` row (JSON diff, reason, actor) and emit
  `intel.config.changed` in the same transaction (`test_a_change_and_its_event_share_one_transaction`).
  Live check on the dev stack: `intel_config activate home 2` then `rollback` produced two
  `audit_entry` rows in `admin_db` (`intel.config.activated home@2`,
  `intel.config.rolled_back home@1`, detail ids and enums only, no reason text).
- Dev stack after migration: `groups@1`, `home@1`, `reels@1`, `video@1` active and
  `home@2` draft, each identical to its package file and valid.

### WP 4.2

- **Queries for 1,050 candidates:** 10 (`features.MAX_QUERIES`), the same for 10 and 200
  candidates (`test_features_queries.py`). No HTTP client is called (requests patched to fail).
- `test_rule_predictor.py` (16 tests): a cold item scores exactly its configured prior,
  each count is monotonic in its score, more reach without more likes lowers the like
  score, every coefficient (`c_aff`, `c_disc`, `c_conv`, `c_dis`, `c_reason`, the priors)
  changes the output when changed in the config, the formula matches 02 section 15.

### WP 4.3

- **Golden test** `feed/tests/test_home_v1_parity.py`: the new path with `home@1` returns the
  identical order to a frozen copy of the pre-phase-4 `rank_items` on 10 fixtures (every
  ranking fixture of `test_hide_rank.py` plus a dense randomized one with timestamp ties,
  stats, flags, favorites, affinities and dislikes). It fails if any `home@1` constant
  changes, and a sensitivity check shows a changed constant does reorder.
- **Dev data, 120 viewers with the most feed rows** (19:58 UTC): 119 identical orders; one
  viewer lost 6 of their own posts in groups whose status is `deleted` (rule E3, the same
  rule post applies), with no reordering. Rank time p50 39 ms, max 86 ms.
- `test_home_v2.py` (16 tests): each `home@2` term moves its item the expected way (group
  pull, likes through the predictions, hides through `score_negative`, shared groups,
  conversation, reshare originality, media quality, freshness), integrity demotes but never
  removes, the v2 query count does not grow with candidates.
- **`home@2` on the dev data** (built from params, then activated for a live check and
  rolled back): sources over 120 viewers: connections 37,446, follow_pull 2,722, groups
  1,563; distinct authors in the first 20 items, median 7 -> 13; rank time p50 65 ms, max
  124 ms; 32 queries for the whole first page (retrieval, eligibility, features, items).
  `scripts/integration/intel_privacy.py --served-only` while `home@2` was active: 14,348 ids
  served (follow_pull 238, groups 382 on the first pages), 0 missing, 0 drops by post.

### WP 4.4

- **Pending reports:** 3 distinct reporters or an open case multiply the value by 0.6 in
  `home@2`; the item stays in the list (`test_integrity_signals_demote_and_never_remove`).
  Discovery keeps excluding them (rule E7, phase 3).
- **Duplicates:** 64-bit SimHash of the excerpt's words and word pairs, Hamming distance
  <= 3; `dup_of` names the oldest live near copy (same author in 30 days, or any public post
  in 24 h); the oldest copy has none; out-of-order events still link the later copy. Dev data
  after `intel_backfill_content` (2,345 posts): 822 hashed (posts with at least 4 words), 304
  linked as copies of 92 originals (the integration suites post the same texts).
- **Bait, gold set of 200 posts** (100 ar, 100 en, 56 bait), threshold 0.5:

  | Set | TP | FP | FN | TN | Precision | Recall |
  |---|---|---|---|---|---|---|
  | All | 49 | 2 | 7 | 142 | **0.961** | **0.875** |
  | Arabic | 25 | 0 | 3 | 72 | 1.000 | 0.893 |
  | English | 24 | 2 | 4 | 70 | 0.923 | 0.857 |

  False positives: "If you agree with the new zoning rules, attend the hearing" and "Please
  share your feedback on the beta". Misses: "double tap", "be honest... answer in the
  replies", "retweet and follow to win" and three Arabic phrasings without a lexicon
  phrase. The seeded dev posts contain no bait (0 of 2,347 scored >= 0.5).
- **Suspect engagement:** a reaction from an account registered less than 24 h ago, or
  past 20 reactions in one minute by one account, is stored but never counted in
  `post_stats` or `affinity`, and its unreact subtracts nothing; counted in
  `intel_suspect_engagement_total{reason}`. Off in `home@1` (thresholds 0), on in `home@2`.

### WP 4.5

- `test_diversity.py` (15 tests) on synthetic lists whose plain order breaks the rules
  (top 30 items from 3 authors, formats in runs of 7): at most 2 items per author on every
  page but the last, no 3 consecutive items of one format in the first 5 pages, no short
  page, nothing lost or added, deterministic, relaxation in the order format, topic, author.
- Dev data, first 60 items, median longest same-format run 6 -> 4 with `home@2`. Longer
  runs remain where only one format is left once the author cap holds (the cap relaxes
  last, as 02 section 17 orders).

### WP 4.10

- **Home session for 1,050 items:** 25,200 bytes of items, 25,401 bytes pickled as the
  cache stores it (limit 26 KB = 26,624). Live: a 500-item session takes 12,201 bytes
  (`STRLEN`) and 12,392 bytes (`MEMORY USAGE`) in `redis-hot` (v1 packed 16,000 hex
  characters for the same 500 items).
- **Next page:** 3 queries for 5 and for 40 items (`test_next_page_queries.py`), 3 on the
  dev data.
- `test_session_v2.py`: group items reach page 3 and later; a post deleted or a block made
  after page 1 is not returned; a hide between pages drops a connection item; a reels
  session lives under its own key and leaves Home's alone; a cursor of another surface is
  refused.

## Tests

| Suite | Result |
|---|---|
| feed (`scripts/test-service.sh feed`) | 531 passed; `makemigrations --check` clean |
| admin | 106 passed |
| new feed tests in this track | 126 (parity 13, schema 23, store 14, features 3, predictor 16, home v2 16, integrity 13, bait gold 3, diversity 15, session 7, next page 3) |
| `scripts/integration/intel_privacy.py` | 0 drops from non-connection sources, 0 missing of 14,348 served (home@1 and home@2) |
| `scripts/smoke_test.py` | all checks passed |
| vitest | 814 passed |
| e2e on :4173 (home-feed, home-modes, feed-hide, intel-signals, reels) | 17 passed |
| ruff check / format | clean |

## Deviations from the plan

- **`max_same_format_run` is 2 in `home@2`**, not 02's 3, so the WP 4.5 criterion "no 3
  consecutive posts of one format" holds (06 section 3 recorded the mismatch).
- **Author quality** (`intel_creator_quality`) is built in WP 6.3. Until then the `quality`
  term uses the media quality of a video item and is skipped for other items; saves,
  completions and watch time have no aggregated counts yet, so their scores are the
  configured priors.
- **Affinity is not time-decayed:** `affinity` has no timestamps until WP 6.3, so the
  relationship term uses `log1p(interactions)` as today.
- **Burst rule** counts one account's reactions per minute; detecting a burst shared by
  a set of accounts is left to 9b.9-B3, which reuses this module.
- **Eligibility now runs on connection rows too** (both versions), so a viewer's own
  posts in a deleted group leave "for you" (one viewer, 6 items on the dev data).
- **`FEED_RANK_WINDOW` and `FEED_RANK_SESSION_TTL` left `settings.py`**: they are
  `window.connections` and `session.ttl_s` of the home config, as is `feedback.snooze_days`.
- Ranked items carry an additive `source` field (the web passes it as `src` to post).
