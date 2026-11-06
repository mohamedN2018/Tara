# R3 track A: visit sessions, exposure ranking, new-since, peek, throttles, ranked fallback

Measured on the dev stack on 2026-11-06, branch `feat/web-social-platform` (HEAD `0f59b6e` plus the R3 working tree of both tracks). **Nothing is committed or pushed.** **`home@1` stays the active Home version.** The three new versions are drafts; nothing was activated, and decision 25 (For You as the default) is not flipped. Spec sources: [09 §R3](../09-unified-roadmap.md), 07 rows 4b.4, 4b.5, 4b.7 and 4b.8 (server part) and its query/Redis budget paragraph, 06 §4.1-4.3, §5.1-5.6, §6.2-6.3, §13, §14 and §20, 08 §7.3 and §7.6, and decisions 20, 24 and 25.

## WPs and where they are

| WP | Status | Where (file:line) |
|---|---|---|
| **A1** models and migrations | done; delivered first and applied on dev | `intel/models.py:72` (`EventType.FEED_DWELL`, also in `CLIENT_EVENT_TYPES`), `:234` (5 engagement columns), `:245` (`ExposureState`), `:527` (`FeedSession`), `:423` (`intel_block_high_idx`); `intel/migrations/0008_engagement_exposure_cols.py`, `0009_feed_session.py`, `0010_home_v2c_drafts.py` |
| **A2** config schema v4 | done | `intel/config/schema.py:38` (`SCHEMA_VERSION = 4`), `:451` (`SESSION` and its v4 keys), `:471` (`PEEK.max_count`), `:482` (`EXPOSURE`), `:501` (`ROTATION`), `:504` (`REVISIT`), `:664` (`V4_SECTIONS`), `:668` (`exposure_ranking`), version rules in `_version_rules`; `defaults/home.json` (package defaults now carry `exposure` and the v4 `session` keys, but no `rotation`); new `defaults/home.v2c.json` |
| **A3** visit classifier | done | `intel/session_ctx.py:159` (`classify`), `:239` (`_write_hash`), `:306` (`finish`), `:325` (`_write_rows`), `:379` (`touch`), `:393` (`meta`), `:406` (`purge`); `intel/tasks.py:45` (`intel.purge_feed_sessions`); `config/settings.py:151` (beat line); `intel/deletion.py:45` |
| **A4** exposure multiplier and rotation | done | `intel/ranking/exposure_rank.py:78` (`prefetch`: one pipelined round trip), `:137` (`multiplier`), `:202` (`new_commenters`), `:238` (`merge`), `:295` (`apply`), `:365` (`floor`); `intel/ranking/home.py` (`rank(..., ctx, pools)`); `intel/ranking/features.py:154` (durable exposure columns in the per-post statement) |
| **A5** new-since, caught-up, peek leak fix | done | `feed/ranking.py:334` (`new_since`), `feed/services.py:503` (`clamp_since`), `:510` (`new_since_count`), `:518` (`peek`, eligibility-checked); `feed/views.py:279` (`_chronological_visit`), `:300` (`_peek`) |
| **A6** throttles | done | `feed/throttles.py:46` (`FeedFirstPageThrottle`), `:54` (`FeedPeekThrottle`); `feed/views.py:150` |
| **A7** ranked cursor fallback | done | `feed/ranking.py:288` (`_oldest`, the `t_min`/`id_min` pair), `:352` (`first_page`, OOM fallback), `:419` (`reuse_page`), `:432` (`_session_page`: forward read and refill), `:484` (`_recheck_entries`: named rule per entry), `:526` (`next_page`); `intel/ranking/session.py:115` (`save` counts OOM), `:134` (`current`), `:147` (`load` counts missing or replaced); `feed/views.py:425` (`REUSE_ENTRIES`) |
| **A8** first-page budget | done (≤ 12 met; the p95 target is met for home@2c but not for r15) | `intel/eligibility.py:370`, `:423` (`load_context`: 2 queries instead of 14); `intel/ranking/features.py:126`, `:178`, `:206` (2 instead of 10); `intel/retrieval/sources.py:110`, `:130` (follow pull: 1 instead of 5); `feed/views.py:472` (one preference row for the mode and `personalization_off`); `intel/head.py:39` (takes the prefetched head and flag) |
| **A9** harness `--simulate-display` | done | `intel/management/commands/intel_measure_repetition.py:587` (`_simulate`), `:759` (`_pre_scores`), `:772` (`_residual`), `:76` (`_deep` for `--override`); `intel/repetition.py` (`repeat_rate`) |

## Acceptance, measured

**Harness runs.** These used `scripts/intel/measure_repetition.py --mount-source` (equivalent `docker run` with the source mounted) on dev data:
- The draft under test was `--variant home@6` (`home@2c`), or `home@7` (`home@2c-r15`).
- Viewers were the 20 accounts with ≥ 60 eligible connection candidates, out of 66 scanned. Their eligible candidates were 356 to 779 (p50 552), plus 179 to 256 pool items.
- Redis was redis-hot db 9, flushed before and after.
- SQL ran in a transaction that was always rolled back.
- After every run, the residual check was `{"intel_feed_session": 0, "intel_signal_event": 0}`.
- Displays were simulated: page-1 items 0 to 7 with 4 s dwell (state `viewed`), the rest as impressions, at the simulated clock, through `exposure.append_records`.
- The JSON outputs are `C:\Users\MOHAME~1\AppData\Local\Temp\claude\f--4-docker-composer-Django-Project-2-Offline-Tara\747ad587-5274-410b-a332-79327bbe7067\scratchpad\sim-home6.json`, `C:\Users\MOHAME~1\AppData\Local\Temp\claude\f--4-docker-composer-Django-Project-2-Offline-Tara\747ad587-5274-410b-a332-79327bbe7067\scratchpad\sim-home7.json` and the tuning run `C:\Users\MOHAME~1\AppData\Local\Temp\claude\f--4-docker-composer-Django-Project-2-Offline-Tara\747ad587-5274-410b-a332-79327bbe7067\scratchpad\sim-home7-tuned.json`.

| Criterion | Target | home@2c | home@2c-r15 |
|---|---|---|---|
| Page-1 Jaccard, A vs B at +45 min: median / p90 | ≤ 0.30 / ≤ 0.50 | **0.00 / 0.00** (max 0.43) | **0.00 / 0.00** (max 0.33) |
| Page-1 Jaccard, A vs B at +6 h: median / p90 | same | **0.00 / 0.00** (max 0.48) | **0.00 / 0.00** (max 0.33) |
| Dwelled-in-A items in B's page 1 | ≤ 1 | p90 **0**, max 6 (one viewer) | p90 **0**, max 5 |
| Consumed-in-A items in B's page 1 | ≤ 1 | **0** (a 4 s dwell is `viewed`, not `consumed`) | **0** |
| Refresh at +60 s, no signals, pools frozen | Jaccard ≥ 0.90 | **1.00** for every viewer | **1.00** |
| Mean pre-multiplier score, B ÷ A | ≥ 0.8 | **0.875** at 45 min, **0.823** at 6 h | **0.875** / **0.823** |
| First-page latency (n = 180, harness host) | p95 ≤ 150 ms | **p50 82, p95 144.5 ms** | p50 109, **p95 207 ms (not met)** |
| First-page queries (n = 180) | ≤ 12 | **p50 10, max 11** | **p50 10, max 11** |
| SQL writes per first page | 2 new, 0 other | 140 × 2 (new visits), 20 × 1 (first visit ever, nothing to close), 20 × 0 (refreshes) | same |
| Scenario C (5 visits 45 min apart × 3 pages, impressions only) | repeat ≤ 10% (06: ≤ 5% on first pages) | first pages mean 38%, all pages 41% (**not met**) | first pages mean **31%** (p50 15%), all pages 33% (**not met**) |

Scenario C is an early run (09 R3) and is **not met**. Diagnosis:
- The repeated items are `displayed` at m = 0.57 after 45 min (06 §5.3: m0 0.55, h 12 h).
- Viewers whose best unseen items are concentrated in a few authors repeat items, because the diversity re-ranker's author cap (2 per page) lets a demoted seen item from another author take the slot (a debug run showed an unseen item with score' 4.9 at rank 206).
- A tuning run under r15 used `--override '{"exposure":{"m0":{"displayed":0.2},"half_life_h":{"displayed":8.67}}}'`. That curve still meets 07's revisit numbers (m ≥ 0.9 at 26 h, and at 34 h for two exposures). It lowered the first-page repeat rate to a mean of 23% (p50 0, p90 70%). This is not adopted: the 06 table values are what the spec gives.

**Unit and API tests.**

| Criterion | Evidence |
|---|---|
| Revisit, displayed: m ≥ 0.9 at +26.1 h after one exposure, < 0.9 at 25.9 h; m² ≥ 0.9 at +40 h after two, < 0.9 at 36 h | `test_exposure_rank.py::test_displayed_recovers_in_26h_after_one_exposure_40h_after_two` |
| Revisit, consumed: m = 0.874 (< 0.9) at +11 d; ≥ 0.9 at +12.5 d with one exposure; < 0.9 at +12.5 d and ≥ 0.9 at +16.5 d with two | `test_consumed_recovers_in_12_5_days_after_one_16_5_after_two` |
| `retrieved` gets no state: a first page, a next page, a pull and a peek leave no `feed:exp` key | `test_exposure_rank.py::test_serving_never_writes_the_ledger`; retrieved-only items keep m = 1 (`test_retrieved_only_keeps_full_score`, carry-over 7 of 7 in `test_displayed_items_sink_and_retrieved_ones_keep_their_place`) |
| SQL writes: 2 on a new visit; 0 on a refresh, an ongoing visit and a next page | `test_feed_session_table.py::test_one_row_per_visit_closed_with_the_counters[for_you, recent]` (it also checks the closed row's counters: first pages 3, refreshes 1, displayed 6, consumed 2); `test_first_page_budget.py` |
| `personalization_off`: 0 rows and 0 visit, ledger or head keys | `test_visit_classify.py::test_personalization_off_stores_nothing[recent, for_you]`, `test_first_page_budget.py::test_personalization_off_reads_no_visit_and_writes_nothing`. `meta.visit` is null |
| home@1 parity and the home@2, home@2b and recent golden tests | `feed/tests/test_home_v1_parity.py`, `intel/tests/test_home_v2.py`, `test_continuation.py`, `test_modes.py`: all green with the batched eligibility and feature reads |
| Peek `new_count` is eligibility-checked; a blocked author's post is invisible to it | `test_peek_since.py` (6 tests: eligible count in `for_you` and `recent`, blocked either way, deleted, clamp, cap 99 with `new_count_capped`, the session is never replaced and ads are never called) |
| `recent`: after +3 days with K = 4 new rows, `anchor_index` = 4 and `caught_up_index` = 4, order unchanged; +45 min later `new_count` = 0 with no divider; a blocked author's new row changes neither the count nor the ids | `test_new_since.py` (the `recent` divider, the block case, and the following, friends and favorites modes) |
| `for_you`: every position i < min(new_count, 30) holds a new-since item or an item scored above the lowest new-since item | `test_new_since.py::test_for_you_new_since_block_leads_the_first_page` |
| Lost session: 0 duplicate ids over 15 pages with inserts, deletes and a hide between pages, for expiry, another tab and a redis-hot restart; an OOM-refused session write serves the ranked head with `fallback=true`, counts `intel_rank_session_oom_total` and continues below `t_min` | `test_ranked_cursor_fallback.py` (8 tests) |
| Every frozen-list entry is served or dropped by a named rule (`visible`, E1, E4, E5); a short page is refilled | `test_every_frozen_entry_is_served_or_dropped_by_a_named_rule` |
| Reload to the same card: `entry=reload` during the visit serves the same ids and `sid`; `pull` re-ranks | `test_a_reload_during_the_visit_reuses_the_frozen_list` |
| The 31st first page in a minute gets 429 with `Retry-After`; cursor pages are not throttled; peek has its own limit of 60; the rates follow the config | `test_feed_throttle.py` (3 tests) |
| ≤ 12 queries | `test_first_page_budget.py` on a test world: ≤ 12 reads for a new visit, a refresh, an ongoing visit and a peek; ≤ 5 for a next page; ≤ 6 for a reused list. Dev harness: max 11 |

**Query breakdown** of a home@2c first page on dev, 10 reads:
- 1: preference row
- 3: connections, follow pull, groups
- 2: eligibility
- 2: features (the durable exposure columns ride in the per-post statement)
- 1: materialize
- 1: new-commenter check (only when an item is demoted below `revisit.min_m`)

A new visit adds the origin lookup for the visit row (11). A redis-hot miss adds the latest-visit read (12).

## Test counts

- `bash scripts/test-service.sh feed` on the rebuilt image: **844 passed, 1 skipped**. The skip is the known infra-file test. `makemigrations --check` reports "No changes detected". The run includes track B's tests in the tree at that moment.
- Track A added about 90 tests:

| File | Tests |
|---|---|
| `test_visit_classify.py` | 22 |
| `test_feed_session_table.py` | 6 |
| `test_exposure_rank.py` | 12 |
| `test_new_since.py` | 6 |
| `test_peek_since.py` | 6 |
| `test_feed_throttle.py` | 3 |
| `test_ranked_cursor_fallback.py` | 8 |
| `test_migrations_r3.py` | 2 |
| `test_first_page_budget.py` | 3 |
| `test_config_schema.py` additions | 19 |
| `test_measure_repetition.py` additions, including an end-to-end `--simulate-display` run | 3 |

- Adjusted to the new contracts:
  - `feed/tests/test_hide_rank.py::test_a_lost_session_falls_back_to_latest_order`: now below `t_min`, no repeats.
  - `test_delivery_config.py`: Home is schema 4.
  - `test_test_clock_guard.py`: the spy takes the new keyword arguments.
- Other checks:
  - `python scripts/smoke_test.py`: all checks passed.
  - `uvx ruff@0.17.3 check .` and `format --check .`: clean.
  - `scripts/intel/check_deploy.sh`: ok.
  - Dokploy size check: 74,994 (unchanged).
- Containers recreated: feed, feed-relay, feed-signals, and feed-consumer (the same image). `migrate` has nothing left to apply. The beat schedule in feed-relay lists `intel-purge-feed-sessions`.

## Migrations, events, env vars, routes

- **Migrations** (additive, applied on dev):
  - `intel/0008_engagement_exposure_cols`: RunSQL `ADD COLUMN` on the partitioned parent, catalog-only, plus the `feed_dwell` choice.
  - `intel/0009_feed_session`: a new table and its indexes, plus the `intel_block_pair(high)` index.
  - `intel/0010_home_v2c_drafts`: drafts `home@2c`, `home@2c-r15` and `home@2c-r30`, which are versions 6, 7 and 8 on dev. Each has a change-log row and no outbox event. The migration is idempotent.
  - Forward and backward runs on an empty and a populated partition: `test_migrations_r3.py`.
- **Events:** none. `intel_feed_session` writes no outbox event.
- **Env vars:** none.
- **Routes:** none. `GET /api/v1/feed/` gains the params `sid` and `entry`. Its first-page `meta` gains `visit`, `refresh_after_s` and `auto_refetch_after_s`, and `caught_up_index` on chronological pages too.
- **Peek response:** `{data, ids, new_count, new_count_capped, since, mode, peek}`.
- **Beat:** `intel.purge_feed_sessions` runs nightly (86,400 s). It is picked up by:
  - the dev feed-relay (`worker -B`, verified in its schedule);
  - the Dokploy `feed-worker` (`worker -B`, `docker-compose.dokploy.yml:858`);
  - the k8s worker component (`-B`, `infra/k8s/components/worker/worker-deployment.yaml:34`).

  No compose change was needed.
- **Metrics:**
  - `intel_rank_session_oom_total`
  - `intel_rank_session_lost_total{reason=missing|replaced}`
  - `intel_feed_visit_total{kind}`
  - `intel_hot_write_failed_total{key="sess"|"rank"}`

## Contract with track B, as delivered

- **`feed:sess:{viewer}` fields** are exactly the contract's:
  - `visit_id`, `visit_ord`, `kind`
  - `visit_started_at`, `prev_visit_started_at`, `last_activity_at`
  - `sid`, `fp:{surface}`
  - `fp`, `rf`, `dc`, `cc`

  Two fields are added for track A's own use: `nc` and `na`, the new-since count and anchor of the visit's last ranked page, so a reused list shows the same divider. A new visit resets the counters in one MULTI/EXEC; the previous values go into the closing UPDATE.
- **Config keys:** `exposure.ledger.cap|ttl_h`, `exposure.*_dwell_ms` and `exposure.length_buckets` resolve under every version through the package defaults (`test_exposure_ranking_needs_the_stored_version_to_carry_rotation`). The `length_buckets` defaults were chosen here because 06 gives none: ≤ 280 chars × 0.75, ≤ 1,000 × 1.0, longer × 1.5. Track B's `Thresholds.consumed_ms` treats the token's bucket as 1-based.
- **Visit ordinal:** `serve_tokens.stamp_home_items(..., visit_ord=)` gets the visit ordinal on every first page. Next pages pass none, because the ordinal is not in the cursor: open item 3.
- **Harness writes:** the harness uses track B's `exposure.append_records` with `Record` values. Its tuple form is `(item, state, minute[, dwell_only])`, so the visit ordinal is stamped from the hash.

## Deviations and why

1. **09's "a consumed one at +11 days" contradicts 06 and 07.** 06 §5.3 computes m = 0.874 at +11 d. The tests use 07's numbers (+12.5 d and +16.5 d) and assert m < 0.9 at +11 d. **The verifier should correct 09's wording.**
2. **`head_overlap` is stored on the new visit's INSERT** (its first head against the previous one), not on the closing UPDATE. It describes the new visit and keeps the 2-write total.
3. **Blocked authors leave every mode's visible rows.** `feed/ranking.py:92` excludes `intel_block_pair` either way, via a fixed `RawSQL` with a bound viewer id. A fan-out racing a block could otherwise show and count a blocked author's row in `recent` (07 4b.7). This adds no query. The index on `intel_block_pair(high)` serves it, and the `recent` golden is unchanged.
4. **A8 changed shared read code.** `eligibility.load_context`, `features.build` and `sources.follow_pull` keep the same data in fewer statements. The parity, golden, property and eligibility suites are green.
5. **The conversation exception is a separate small read** (+1, only when an item is demoted below `revisit.min_m`, and for at most 60 such items). The first design counted commenters inside the per-post statement. Its correlated estimate (cost 1.4 × 10⁹) made PostgreSQL JIT-compile the statement: 488 ms of 497 ms.
6. **Config key `revisit.min_m` (0.8) was added** so the exception's floor is not a literal (decision 20).
7. **The throttle rates are read from the active config per request.** They are not settings lines, so the settings file only gained the beat line.
8. **Query counts exclude SAVEPOINT/RELEASE**, which come from `ATOMIC_REQUESTS` in tests. The once-per-account age-class capture (WP 4b.14) is warmed before measuring.
9. **`meta.visit.since` is ISO 8601**, like `as_of`. `?since=` accepts ISO or epoch. `anchor_index` is null when nothing is new or the count is capped.
10. **On an OOM-refused session write** (planner note 9) the ranked head is served with `fallback=true` and a chronological continuation below the head's `t_min`. 08 serves a chronological first page instead. Both give 0 duplicates.
11. **The chronological peek counts the mode's own page rows** (the same queryset as the page), so a post that `post.deleted` has not yet removed counts as it shows. The `for_you` peek runs the eligibility rules.
12. **`personalization_off` still writes two keys:** the ranking-session pager (WP 4.10, which existed before) and the account's own age-class memo (WP 4b.14, safety data). No visit, ledger, head or row is written.

## Open items

1. **Scenario C repeat rate is about 31% under r15** (target ≤ 10%). The cause is described under Acceptance. A decision is needed: a steeper `displayed` curve in the drafts, an author-cap relaxation that prefers an unseen item over a seen one, or both. Every value is already a config key.
2. **`home@2c-r15` first-page p95 is 207 ms** against a target of 150 (home@2c: 144.5 ms). The time goes to the Python diversity re-ranker over about 750 candidates once the pools are scored. Next step: cap the re-ranked prefix, since only the first pages need diversity.
3. **Next pages pass no `visit_ord` to `stamp_home_items`.** It would need the ordinal in the ranked cursor and a keyset field for the chronological cursor.
4. **`comment_state` has no index on `post_id` or `author_id`** (only the primary key). The feature commenter count and the conversation exception scan it (2,843 rows on dev). It needs an index migration in the feed app before production scale.
5. **For the verifier:**
   - Merge this report with track B's into `results/r3.md`.
   - Record the harness run in `results/phase-04b.md`.
   - Correct 09's "+11 days".
   - Watch the e2e and smoke runs for the new 30-per-minute first-page 429.
