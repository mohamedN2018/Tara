# Phase 4 results: rule-based ranking and the central config

Date: 2026-11-05. Dev stack as in [phase-03.md](phase-03.md) (Docker Desktop, Windows 11,
seeded dataset in `.seed-state/`, nothing wiped). Two build tracks delivered the work
packages:

- **Track A** (WP 4.1 to 4.5 and 4.10): config store, features and predictions, Home
  ranker, integrity, diversity, session v2. Notes: [phase-04-track-a.md](phase-04-track-a.md).
- **Track B** (WP 4.6 to 4.9 and 4.11): modes, peek, why-this, ad slots, ads billing.
  Notes: [phase-04-track-b.md](phase-04-track-b.md).

The last section, "Verification", is the adversarial review of both tracks: what was
re-checked, the problems found and their fixes. Every count below was taken by a query or
a run at the time shown, never compared with a fixed number (04, section 0).

All outputs of the rules are **scores** (`score_*`, `calibrated=False`), not
probabilities. No LLM and no external call takes part in ranking.

## Status per work package

| WP | Status | Where |
|---|---|---|
| 4.1 Config store | Done | `services/feed/intel/config/{schema,store,__init__}.py`, `defaults/home.json` (= `home@1`), `defaults/home.v2.json`, models `RankingConfig` / `RankingConfigChange` (`intel/models.py`), migration `intel/0004_ranking_config` (tables, one-active partial unique index, immutability trigger, version-1 load, `home@2` draft), `manage.py intel_config`, event `intel.config.changed` (`libs/tara_events/.../intel.config.changed.v1.json`), admin handler `audit_intel_config_changed` (`services/admin/adminsvc/handlers.py`) |
| 4.2 Features and predictions | Done | `intel/ranking/features.py`, `intel/predictions/{base,rules,__init__}.py` (`RulePredictor`) |
| 4.3 Home ranker | Done | `intel/ranking/{home,scorer,explain}.py`; `feed/ranking.py::rank_items` and `first_page` always delegate to `intel.ranking.home.rank` |
| 4.4 Integrity | Done | `intel/integrity.py`, lexicons `intel/topics/lexicons/bait_{ar,en}.txt`, gold set `intel/tests/fixtures/bait_gold.jsonl`, `ContentRef.dup_of` (`intel/0005`), `ReactionState.suspect` and `AuthorRef.registered_at` (`feed/0010`), `account.registered` consumer |
| 4.5 Diversity re-ranker | Done (verifier: page-boundary and beyond-window fixes) | `intel/ranking/diversity.py` |
| 4.6 Modes and remembered mode | Done | `feed/services.py` (`MODES`, `friends`), `feed/views.py::_mode`, `intel/preferences.py`, `intel/models.py` (`FeedMode`, `UserPreference`), migration `intel/0003_user_preference`, `intel/views.py::PreferencesView` (`GET/PATCH /api/v1/feed/preferences/`), `intel/deletion.py`; web `services/feed.ts`, `views/HomeView.vue`, `i18n/homeFeed.{ar,en}.ts` |
| 4.7 Realtime peek (D4) | Done | `feed/views.py::_peek`, `feed/services.py::peek`, web `HomeView.vue::addFromTop`, `services/feed.ts::peek` |
| 4.8 Why-this v2 | Done | `intel/why.py`, `intel/views.py::WhyView` (`GET /api/v1/feed/why/{type}/{id}/`), web `components/post/WhyThisPost.vue`, `PostCard.vue`, `lib/signals.ts`, `i18n/postsFeed.{ar,en}.ts` |
| 4.9 Ad slots from config | Done | `feed/views.py::ad_slots`, `sponsored_for_slots`, `meta.ad_slots`; `home.json` `ads.slots: [4]`; web `HomeView.vue::adAt` |
| 4.10 Ranking session v2 | Done | `intel/ranking/session.py`, `intel/eligibility.py::recheck`, `feed/ranking.py` (`first_page`, `next_page`) |
| 4.11 Ads payment check (D13) | Done (verifier: billable events too) | `services/ads/ads/services.py` (`eligible_creatives`, `record_event`), `ads/models.py` (`AdvertiserAccount.BILLING_ACTIVE`) |

## Acceptance evidence

### WP 4.1 Config store

- **Invalid params are rejected:** `test_config_schema.py` (24 tests): unknown sections and
  keys, weights outside [-10, 10], NaN, strings, booleans, half-life <= 0, ratios that do not
  sum to 1, multipliers outside (0, 1], bad Beta priors, unknown reasons or sources, the
  wrong surface, and (verifier) switches whose other value is not built and Home sources
  without a retriever. `store.create` and `store.activate` both validate.
- **An active version is immutable:** the model refuses a params change, and the trigger
  `intel_rcfg_immutable` rejects a raw SQL `UPDATE ... SET params` and any `DELETE` of a
  non-draft row (`test_config_store.py`, 14 tests).
- **Every change is audited:** create, activate and rollback write an
  `intel_ranking_config_change` row and emit `intel.config.changed` through the outbox in
  the same transaction. Admin turns it into an `AuditEntry` (`test_intel_audit.py`, 3
  tests). Live check by track A: `activate home 2`, then `rollback`, gave exactly 2
  `audit_entry` rows, with ids and enums only and no reason text. `home@1` is active again.

### WP 4.2 Features and predictions

- **Queries for 1,050 candidates:** 10, the same for 10 and 200 candidates
  (`test_features_queries.py`, `CaptureQueriesContext`). Limit: 12.
- **No cross-service call:** `requests` is patched to fail in the test, and there is no
  `mutual_count`.
- **`RulePredictor`** (`test_rule_predictor.py`, 16 tests):
  - priors;
  - monotonicity;
  - a cold item scores exactly its prior;
  - every coefficient and prior is read from the `predictor` block.

### WP 4.3 Home ranker

- **Golden parity:** `feed/tests/test_home_v1_parity.py` (13 tests). The new scorer with
  `home@1` gives the identical order to a frozen copy of the pre-phase-4 `rank_items`.
  - It covers every ranking fixture of `test_hide_rank.py`, plus a dense fixture with
    timestamp ties.
  - It fails if any `home@1` constant changes.
- **`home@2` terms:** `test_home_v2.py` (16 tests). Each term moves its item in the
  expected direction.
- **Dev data** (track A, 120 viewers):
  - 119 identical orders.
  - One viewer lost 6 of their own posts that sit in deleted groups (rule E3). Nothing was
    reordered.

### WP 4.4 Integrity

- **Demotion, never removal:** pending reports, duplicates (except the oldest copy), bait
  and spam flags only multiply the value (`test_integrity.py`, 13 tests). They are all
  1.0 in `home@1` and active in `home@2`.
- **Bait on the gold set** (200 posts: 100 ar and 100 en, 56 bait), threshold 0.5, from
  `test_bait_gold.py`:

  | Set | Precision | Recall |
  |---|---|---|
  | All | **0.961** | **0.875** |
  | Arabic | 1.000 | 0.893 |
  | English | 0.923 | 0.857 |

  The thresholds are precision ≥ 0.8 and recall ≥ 0.5.
- **Duplicates on dev data:** 304 posts are linked as copies of 92 originals.
- **Suspect reactions:** a suspect reaction is stored but never counted in `post_stats` or
  `affinity`. Both rules are off in `home@1`.

### WP 4.5 Diversity re-ranker

**Synthetic data** (`test_diversity.py`, 17 tests):
- at most 2 posts per author per page;
- no 3 consecutive items of one format;
- no page shorter than the page size;
- deterministic;
- constraints relax in the order format, topic, author;
- (verifier) no run and no author-gap break across a page boundary;
- (verifier) alternatives past the window are used before the author cap relaxes.

**Dev data, `home@2`, 60 viewers, first 60 items:**

| Measure | Before the verifier's fix | After |
|---|---|---|
| Pages with more than 2 posts by one author | 118 of 180 | 11 |
| Runs of 3 items of one format | 133 | 18 |

The pages that still break a rule belong to viewers whose remaining list has no
alternative (for example, 3 viewers have 10 authors or fewer in total).

### WP 4.6 Modes and remembered mode

- **All 5 modes are served and echoed back:** `test_modes.py` (15 tests).
  - `friends` keeps `reason=friend` rows only, newest first.
  - Precedence: `?mode=`, then the remembered mode, then `mode_hint`, then `recent`.
  - `PATCH` uses a `version` check and returns 409 on a stale write.
- **Live probe (verifier), 38 seeded viewers, every mode, pages 1 to 3, through the real
  view:**
  - every response is 200;
  - the mode is echoed back;
  - no repeats within a ranked session;
  - every served item is authorized.

  Served items: recent 1,631, for_you 1,631, friends 1,623, following 1,500, favorites 0.
  The seed has no favorites.
- **The mode survives a new browser:** the e2e `home-modes.spec.ts` (ar and en) opens a
  second context with empty storage and finds Friends selected.

### WP 4.7 Realtime peek

- `test_peek_does_not_replace_session.py` (11 tests): after a peek the session is
  byte-identical, and ads are called once, for page 1 only. Page 2 has `fallback: false`
  and no repeats.
- Live probe: a peek in every mode returns 200, and every peeked item is authorized.

### WP 4.8 Why-this v2

- `test_why.py` (16 tests):
  - 9 cases give the identical 404 body: missing, invisible, not served, another viewer's
    token, an expired or forged token, a token for another item, a non-uuid, and a
    non-post type.
  - A served item gives 200.
  - After a hide, unfollow, block or group ban, the item gives 404.
  - E9 applies to a viewer of unknown age.
  - The body contains no other users' data.
  - A sensitive topic is masked.
- Web: `whyThisPost.spec.ts` checks the en text and the ar text with `dir="rtl"`.
- **Live probe:**
  - with the item's token: 213 of 213 return 200 (134 with `home@1` active, 79 with `home@2`);
  - for a non-public post the viewer has no row for and no proof: 58 of 58 return 404.

### WP 4.9 Ad slots from config

- `test_ads_separation.py` (12 tests): the organic order is identical with ads on and
  off, in all 5 modes and on every page.
- The default `[4]` puts one ad at the same index as before, or in the rail.
- A second ad appears only with `[4, 14]`, and the same creative never fills two slots.
- The web `homeFeed.spec.ts` checks that the ad position matches the old one.
- Live probe: `meta.ad_slots == [4]` on every first page.

### WP 4.10 Ranking session v2

- **Size:** a 1,050-item session is 25,200 B of items, or 25,401 B as stored (limit
  26,624 B).
- **Next page:** 3 queries (`test_next_page_queries.py`; limit 5).
- `test_session_v2.py`:
  - group items reach page 3;
  - a post deleted, or a block made, after page 1 is not returned;
  - a hide between pages drops the item;
  - a reels session leaves Home's alone;
  - a cursor of another surface is refused.

### WP 4.11 Ads payment check

- `test_billing_status_excluded.py` (14 tests):
  - 8 non-active `billing_status` values never serve;
  - the active control serves;
  - reactivation serves again;
  - `ads.E001` still fires in production;
  - (verifier) an advertiser that is not active records no billable impression or click.

## Tests (final run, after the verifier's fixes)

| Check | Result |
|---|---|
| feed, `scripts/test-service.sh feed` (image rebuilt) | **534 passed**; `makemigrations --check` clean |
| admin, `scripts/test-service.sh admin` | **106 passed**; clean |
| ads, `scripts/test-service.sh ads` (image rebuilt) | **102 passed**; clean |
| `python scripts/smoke_test.py` (after recreating feed, feed-signals, feed-consumer, feed-relay, ads) | all checks passed |
| `uvx ruff@0.17.3 check` / `format --check` (feed, ads, admin) | clean |
| web lint / typecheck | clean |
| web vitest | **814 passed** (58 files) |
| `VITE_STORAGE_PROXY=true npm run build` | built |
| e2e on :4173 | **21 passed**: `home-feed`, `home-modes`, `feed-hide`, `intel-signals`, `t4-visibility` (15), `reels` (6) |
| Live probe (`verify4/probe.py`, read-only, sessions in a throwaway `redis-hot` db, ads stubbed) | 0 problems; details in the Verification section |

## Migrations, events, env vars, routes

**Migrations** are all additive and applied on dev:
- `intel/0003_user_preference`
- `intel/0004_ranking_config` (data load and trigger)
- `intel/0005_content_integrity`
- `feed/0010_integrity_signals` (index built concurrently)

**Events:**
- New: `intel.config.changed` v1. Its producer is feed and its consumer is admin. It is
  listed in `docs/architecture/phase-0/04-event-contracts.md`.
- Feed now consumes `account.registered`.

**Env var:** `INTEL_EMIT_CONFIG_CHANGED` (default `true`) is set in:
- `.env.example`
- `.env_prod.example`
- `docker-compose.dokploy.yml` (in the `feed-env` anchor; Dokploy size check: 74,722, under 100,000)
- `infra/compose/docker-compose.yml`
- `scripts/gen-dokploy-env.sh`
- `docs/deploy/DOKPLOY.md`
- `infra/k8s/overlays/feed/configmap.yaml` (added by the verifier)

**Routes:** `/api/v1/feed/preferences/` and `/api/v1/feed/why/...` sit under the existing
`/api/v1/feed` prefix (Traefik, `nginx.conf`, k8s ingress), so no route change is needed.

## Deviations from the plan

- **`max_same_format_run` is 2 in `home@2`** (02 says 3), so the "no 3 in a row" criterion
  holds.
- **Track A, signals that arrive later:**
  - the `quality` term uses video media quality only, because author quality arrives in
    WP 6.3;
  - saves, completions and watch time score their configured priors;
  - affinity is not time-decayed.
- **The burst rule** counts per account. Detecting a burst shared by a set of accounts is
  not done.
- **Eligibility also runs on connection rows** (both versions).
- **Settings moved into the home config:** `FEED_RANK_WINDOW`, `FEED_RANK_SESSION_TTL` and
  `SNOOZE_DAYS` are now config keys.
- **Ranked items carry an additive `source` field.**
- **Track B:**
  - only switcher taps are remembered, not `?mode=` links;
  - the "recent" label stays «الأحدث» / "Latest";
  - `sponsored_slots` is new, and `sponsored` still holds the first ad;
  - topic factors have no producer until phase 6.
- **Diversity (verifier):**
  - the window is still `window_factor × page_size` for the MMR choice;
  - when no item in the window meets the constraints, the rest of the list is searched in
    score order before a constraint relaxes;
  - the format run and the author gap now count the tail of the previous page.

  02 section 17 only names the window. The change makes "≤ 2 per author per page … when
  alternatives exist" hold on real data. The re-ranker's cost rises from 42 ms to 50 ms
  p50 and from 78 ms to 124 ms max on dev data.
- **Unbuilt switches (verifier):** `modes.recent_includes_groups` accepts only `false`,
  and `ads.first_page_only` only `true`. Home `ranking.sources` accepts only the sources
  with a retriever (`connections`, `follow_pull`, `groups`). Before, these were toggles
  that did nothing, or (for `reels`/`video`) a `KeyError` on every Home request.

## Verification

The verifier re-ran every suite and probed the dev data through the real views; it did
not rely on the track reports.

### Checks that found nothing

**Authorization:**
- The live probe checked every item served in every mode, the peeks, and pages 1 to 3, for
  38 viewers with `home@1` and 20 with `home@2` (patched in, never activated).
- A connection item must be in the viewer's `visible_items`.
- Any other item must pass `eligibility.filter` with the viewer's claims.
- Result: 0 unauthorized items, 0 repeats in ranked sessions.

**Group posts in fan-out rows:** only the authors' own rows exist (58 public, 10 private,
6 in deleted groups). No friend or follower receives a group post through fan-out, so the
chronological modes leak none.

**Why-this:** results are listed under WP 4.8.

**Weights and thresholds:**
- All are read from the config.
- The remaining literals are a numerical guard (`_EPS`), the cache TTL of the config
  pointer (`ACTIVE_TTL_S`), and the wire tables of session v2.

**Transactions:** `intel.config.changed` is recorded inside the `atomic()` block that
writes the change row.

**Synthetic data:** ranking reads only aggregates (`post_stats`, `affinity`,
`intel_content_ref`), never raw signals, so `INTEL_SYNTHETIC_IN_RANKING` stays out of the
path.

### Problems found and fixed

1. **Diversity broke its own limits on real data** (`intel/ranking/diversity.py`).
   - **Cause:** the re-ranker only looked at the top 60 items. When a few prolific authors
     filled that window, the author cap and the format rule relaxed, even though other
     authors existed further down.
   - **Cause:** each page started with an empty history, so a run of one format, or the
     author gap, carried on across page boundaries.
   - **Effect on dev data:** 118 of 180 pages broke the author cap, and there were 133
     runs of 3.
   - **Fix:**
     - the history now carries over from the previous page (`_Page.seq`);
     - before a constraint relaxes, the rest of the list is searched;
     - `_Beyond` keeps exact counts of authors and formats past the window, so that
       search is skipped when it cannot succeed.
   - **Tests:** `test_format_runs_and_author_gaps_do_not_continue_across_pages` and
     `test_alternatives_past_the_window_keep_the_author_cap`.
2. **No-op or crashing config switches** (`intel/config/schema.py`).
   - **Cause:** the schema accepted `modes.recent_includes_groups: true` and
     `ads.first_page_only: false`, but no code reads either value. It also accepted
     `reels` or `video` in `home.ranking.sources`, which has no Home retriever and raises
     a `KeyError` in `home.inventory`.
   - **Fix:** a new `Fixed` spec, and `HOME_RANKING` restricted to `HOME_SOURCES`.
   - **Test:** `test_switches_that_are_not_built_yet_only_take_their_built_value`. It also
     asserts that `HOME_SOURCES` equals `home.SOURCE_FUNCS`.
3. **A suspended advertiser could still be billed** (`ads/services.py::record_event`).
   - **Cause:** serving checked billing, but `record_event` did not. An ad rendered before
     a suspension still recorded impressions and clicks, debited the budget and emitted
     `ad.impression.recorded`.
   - **Fix:** the billing status is now checked under the campaign lock, and a mismatch
     returns 409.
   - **Test:** `test_non_active_billing_records_no_billable_event` (impression, click).
4. **The new env var was missing from k8s.** `INTEL_EMIT_CONFIG_CHANGED` is now in
   `infra/k8s/overlays/feed/configmap.yaml`.

## Open items

- **`home@2` first-page cost:** 32 queries, and about 104 ms p50 / 175 ms max on dev data,
  including the re-ranker. The budget in 02 §22 is ≤ 12 queries and 150 ms p95, re-checked
  in WP 13.2. The MMR window itself is most of the re-ranker's 50 ms, and it is the first
  thing to optimise.
- **`store.update_draft`** changes a draft without a change-log row. Drafts are never
  served, and activation logs the full diff against the active version. Auditing draft
  edits needs a new `action` value in `intel.config.changed` (a schema enum addition).
- **The bait gold set** was written and labelled by the agent that wrote the lexicon, so
  0.961 / 0.875 is optimistic. A human-labelled set drawn from real posts should replace
  it before `home@2` is activated.
- **The `home@1` row in each database** is a snapshot of `home.json` at migration time.
  - Sections and keys added to the file later fall back to the file's defaults.
  - A changed value only applies through a new version.
- **Session v2 and why-this:** `intel/why.py` depends on the session format
  (`rank_session.contains`). A change to session v2 must re-run `test_why.py`.
- **`recheck` does not re-run E6:** it treats authors as active, because the plan's list
  has no E6. An author deactivated between pages is caught by E1, since their content is
  held.
