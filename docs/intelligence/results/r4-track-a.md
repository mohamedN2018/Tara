# R4 track A: interests, feedback, My Algorithm API, experiment core, shared contracts (feed)

Measured on the dev stack on 2026-11-06, branch `feat/web-social-platform` (HEAD `e9b68a9` plus the R4 working tree of both tracks). **Nothing is committed or pushed.** `home@1` stays the active Home version; `home@3`, `home@3-r15` and `home@3-r30` are **drafts** (versions 9, 10 and 11 on dev); decision 25 (For You as the default) is not flipped; **no experiment was started on dev**. Sources: 09 §4 R4; 04 phases 5.4, 5.5, 6, 7, 8; 07 rows 6.3-B2 to 8.7-B2; 06 §4.4, §4.5, §7, §10, §13, §16, §20; 02 §8.1, §10, §13, §14, §20; 03 §2.3 to §2.7, §4.2, §4.3; decisions 2, 7, 8, 9, 11, 12, 13, 17, 20, 23, 24, 25, 37.

**A0 was in place at 2026-11-06 06:12 +02:00 (04:12 UTC)**: `bucketing.py`, `signal_terms.py`, the parity fixture (240 cases, 0 mismatches against the web function run under node 24), the 8 schemas and their rows in `docs/architecture/phase-0/04-event-contracts.md`.

## WPs and where they are

| WP | Status | Where (file:line) |
|---|---|---|
| A0 bucketing | done | `libs/tara_common/tara_common/bucketing.py:35` (`bucket`, FNV-1a over UTF-16 code units), `:42` (`assign_variant`, 10,000 buckets of `key:salt`, cumulative `pct*100`); fixture `services/feed/intel/tests/fixtures/bucket_parity.json` (generator recorded in the file) |
| A0 signal terms | done | `libs/tara_common/tara_common/signal_terms.py:25` (`tokens`), `:40` (`term_keys`, sha256, >= 2 chars, <= 8), `:45` (`alias_key`) |
| A0 schemas | done | `libs/tara_events/tara_events/schemas/{intel.config.published, intel.experiment.exposed, intel.integrity.flagged, account.updated, feed.recommendations.reset, intel.creator.hidden, intel.search_signal.changed, search.queried}.v1.json` (all `additionalProperties: false`); contracts in `04-event-contracts.md` (Feed table + "R4 events produced outside feed") |
| 5.4 experiment core | done | `intel/experiments.py:78` (`running`: read with the active config, no query of its own), `:96` (`assign`), `:107` (`config_for`), `:127` (`record_exposure`, `ON CONFLICT DO NOTHING` + cache marker), `:211`/`:232` (`start`/`stop`: change-log row, `intel.config.changed`, `intel.config.published`, one transaction); models `intel/models.py` (`Experiment`, `ExperimentExposure`, partial unique "one running per surface"); `intel/config/store.py` (`_ACTIVE_SQL`, `running_experiment`); command `intel/management/commands/intel_experiment.py`; first page `feed/views.py:224` |
| 5.5 config distribution | done | `intel/experiments.py:251` (`published_payload`), `:282` (`publish`); emitted from `intel/config/store.py:302` (activate / rollback) and start / stop; `intel_config publish --surface X` (`intel/management/commands/intel_config.py`); `defaults/discovery.json` + schema `intel/config/schema.py:849`; `discovery@1` seeded active by `intel/migrations/0012_r4_config.py`; consumer `intel/handlers.py:350` (`intel.experiment.exposed`) |
| 6.1 taxonomy | done | `intel/topics/taxonomy.py` (42 topics; group, market, page categories; curated and unmapped hashtags); `intel/topics/lexicons/{ar,en}.txt`; `intel/management/commands/intel_seed_topics.py` (additive, run-time hashtag report) |
| 6.2 classifier | done | `intel/topics/classify.py:159` (`classify`: hashtag 0.9, page/group 0.6, lexicon 2 hits or 1 strong, inherited x0.8, <= 3), `:227` (`classify_post`), hook `intel/readmodel_handlers.py` (`post.created` / `post.updated`), page category `intel/readmodels.py` (`_category`, `intel_page_ref.category_norm`); backfill `intel/management/commands/intel_classify_topics.py`; gold set `intel/tests/fixtures/topic_gold.jsonl` |
| 6.3 / 6.3-B2 aggregators | done | `intel/signals/interests_agg.py:123` (in the same 60 s job, `aggregate.run`), exactly once (`intel_aggregate_watermark`, moved in the delta transaction); tiers and emerging `intel/interests.py:62`, `:77`, `:90`; nightly `intel/creator_quality.py:98` (`intel.rebuild_creator_quality`); weights in `interests.event_weights` incl. `group_join` +2, `group_leave` -1, `topic_explore` +0.5; group join/leave bus rows `intel/readmodel_handlers.py` |
| 6.4 / 8.5-B2 profile API | done | `intel/interests.py` (`profile_view`), `intel/api.py` (`ProfileView`, `ProfileRowView`), `intel/urls.py` |
| 6.5 interest_rel | done | `intel/ranking/home.py:173` (`_personalize`), `intel/interests.py:241` (`interest_rel`), gate `intel/config/schema.py:890` (`interest_ranking`: only versions carrying `interest_rank`), drafts `defaults/home.v3.json` + `intel/migrations/0012_r4_config.py`; profile cache `intel:prof` (`intel/interests.py`, `cached_profile` / `store_profile`), a miss filled from the eligibility statement (`intel/eligibility.py` `'prof'` rows, `intel/ranking/home.py` in `rank`) |
| 6.5-B2 session vector | done | `intel/session_ctx.py:431` (`_SI_LUA`, one `EVAL`: decay, add, evict, TTL), `:491` (`si_update`), `:519` (`si_decode`), `:550` (`session_rel`); ingest `intel/signals/ingest.py:251`, `:261` (from serve-token v2 topic / format / author prefix, no read); bus consumer `intel/handlers.py:286` (`session_vector_bus`: likes, comments, shares, saves; reports and hides -1.0); serve tokens carry the primary topic `intel/ranking/serve_tokens.py` (`stamp_home_items(..., topics=)`); `weights.session` 0.8 in `home@3*` |
| 6.6 / 6.6-B2 cold start | done | onboarding `intel/preferences/service.py:408` + `intel/api.py` (`OnboardingView`); language read model `intel/handlers.py:329` (`account.updated` -> `intel_account_language`); E10 language `feed/views.py` (`_languages`); basic pools unchanged (4b.6) |
| 6.7 (feed side) | done | `intel/handlers.py:329` |
| 6.8-B2 intent v0 | done (shadow) | `intel/intent.py:59` (`classify`), `:68` (`finalize`), `:76` (`overlay`, weight 0), `:97` (`store`); `intel_feed_session.intent` via `intel/session_ctx.py` (`finish(..., intent=)`); wiring `intel/ranking/home.py:407`, `feed/views.py` |
| 7.1 FeedbackService | done | `intel/feedback.py:134` (`act`: action row + exact `before` snapshot + server signal row + interest change, one transaction), `:240` (`undo`: exact restore), `:265` (`resolve_item`: served or own feed, still visible, else 404); `intel/api.py` (`FeedbackView`, `FeedbackUndoView`, throttle `intel_feedback` 120/min) |
| 7.2 effects | done | `feedback_effects` block (`defaults/home.json`); `reel.hidden` consumer `intel/handlers.py:388`; legacy test replaced in `feed/tests/test_hide_rank.py` (comment) by `intel/tests/test_feedback_effects.py::test_not_interested_feedback_downweights_the_author_explicitly` |
| 7.4 integrity | done | `intel/integrity_flags.py:27` (`check`, called from `feed/views.py` `HideView`), `intel_integrity_flag` (cooldown `integrity.flag_cooldown_h` 24, `flag_min_accounts` 3, `spam_flag_rate_threshold`) |
| 7.5-B2 mute / hide creator | done | E8 `intel/eligibility.py:268` (hidden creators, muted and disliked topics; also on later pages: `RECHECK` gains E8, `:639`); muted primary demotion `intel/ranking/home.py:196` (`_preference_multipliers`, x0.3 at confidence >= 0.6); `intel.creator.hidden` `intel/feedback.py:101` (and on undo / profile delete) |
| 7.6-B2 reason codes | done | `intel/why.py:70` (`NEW_CODES`), `:103` (`_interest_factor`), `:131` (`_guard`), `intel/ranking/explain.py` (factor codes `session`, `format_pref`, `muted_topic` appended) |
| 8.1 preferences | done | package `intel/preferences/` (`__init__.py` keeps `intel.preferences`); `service.py:340` (`patch`, optimistic version, change log), `:382` (`undo`), `:457` (debug consent), `:301` (`purge_behaviour`); columns `reset_at`, `search_signal`, `home_sections` (`intel/models.py`) |
| personalization_off | done | turning it on: `service.py` `_side_effects` -> `purge_behaviour` (visit rows now; `hot.purge_behaviour` after commit, fail-soft, `intel_hot_purge_failed_total`); bus and server rows gated (`intel/handlers.py` `_record`, `intel/signals/server.py`); `for_you` served chronologically with `meta.personalization_off` (`feed/views.py:254`); no visit hash, so no touches |
| 8.3 effects in ranking | done | `intel/ranking/personal.py:32` (`share` per discovery level, `format_multiplier`, `viewer`: E10 languages, `other_languages`, toggles), rule E12 `intel/eligibility.py:325` |
| 8.4-B2 reset | done | `service.py:482` (step 1 token), `:518` (step 2: throttle, `reset_at`, change log, `feed.recommendations.reset`, purge, task on commit), `:565` (`run_reset`: one `DELETE` per weekly engagement partition, inferred interests, `affinity`, visit rows, keys); task `intel.reset_recommendations` (`intel/tasks.py`); the aggregators skip rows before `reset_at` |
| 8.7-B2 search signal | done | emit `service.py` (`_emit_search_signal`, enabled = search_signal AND NOT personalization_off); consumer `intel/handlers.py:370` + `intel/search_signal.py:70` (digests matched against `alias_key` of keyword and hashtag aliases in process; topics of the last 3 searches in `feed:si.q`; no digest, no text, no row) |
| deletion | done | `intel/deletion.py` (`intel_content_topic`, `intel_user_interest` incl. other viewers' creator rows, `intel_feedback_action`, `intel_preference_change`, `intel_debug_consent`, `intel_experiment_exposure`, `intel_account_language`, `intel_creator_quality`, `intel_integrity_flag`; taxonomy, experiments and watermark in `NOT_ACCOUNT_KEYED`) |
| purge beat | done | `intel/retention.py:19` (`intel.purge_preference_logs`: 180 / 365 / 90 days, `retention` block) |

## Acceptance, measured

**Harness (09 R4 ask).** `python scripts/intel/measure_repetition.py --mount-source -- --variant home@10 --simulate-display --modes for_you --min-connections 60 --users 20` (home@10 = `home@3-r15`), dev data with the real interest rows the R4 aggregator had built from dev signals (113 creator, 84 format, 62 lang, 45 topic rows), redis-hot throwaway db, SQL rolled back, residual `{"intel_feed_session": 0, "intel_signal_event": 0}`. Output: `C:\Users\MOHAME~1\AppData\Local\Temp\claude\f--4-docker-composer-Django-Project-2-Offline-Tara\747ad587-5274-410b-a332-79327bbe7067\scratchpad\r4a\sim-home10b.json`.

| Criterion | Target | home@3-r15 (measured) | R3 home@2c-r15 |
|---|---|---|---|
| First-page latency, n = 180 | p95 <= 150 ms | **p50 76.8, p95 134.0 ms** | p95 115.4 |
| Queries per first page, n = 180 | <= 12 | **p50 10, p95 11, max 12** | max 12 |
| SQL writes per first page | 2 new / 0 other | 141 x 2, 19 x 1 (first visit ever), 20 x 0 | same |
| Page-1 Jaccard +45 min / +6 h (median, p90) | <= 0.30 / <= 0.50 | 0 / 0 (max 0) | 0 / 0 |
| Consumed-in-A on B's page 1 | <= 1 | 0 / 0 | 0 |
| Refresh after 60 s | >= 0.90 | 1.00 | 1.00 |
| B / A relevance (+45 min / +6 h) | >= 0.8 | 0.871 / 0.822 | 0.872 / 0.819 |
| Scenario C first pages | <= 5% | 25.7% (**not met**, unchanged from R3: R3 open item 1, exposure values are home@2c's) | 25.8% |

The first harness run (before the budget work) measured **max 15 queries**: the running-experiment lookup (1 per 30 s per process), the taxonomy cache (2 per 300 s) and the profile read on an `intel:prof` miss (1 per viewer per 10 min). All three were moved into statements that run anyway: the experiment rides in the active-config read (`store._ACTIVE_SQL`), topic labels in the topic rows of the eligibility statement (and in the one chronological topics read), and a profile miss is filled from `'prof'` rows of the eligibility relations statement, then cached. `test_first_page_budget.py::test_first_page_budget_under_home_3_r15_with_a_profile_miss` pins it (<= 12 with cold caches).

**Ingest** (`bench_ingest_with_ledger.py`, 50 events with serve-token v2 incl. a primary topic): **p50 14.1 ms, p95 18.4 ms** (budget 30), Redis round trips median 2 (the ledger + the session-vector `EVAL`), ledger 2,600 B compacted, max 5,200 B.

**Classifier (6.2).**
- Precision on the 200-post gold set (`topic_gold.jsonl`): **73 of 76 returned topics correct = 0.961** (target 0.8); recall 0.566 (65 of 200 posts get a topic; 89 have gold topics). **Labelled by the R4 track A agent (Claude) reading each post's text; not reviewed by a human.** 111 of the 200 sampled dev posts are test filler ("نص طويل", "منشور تجريبي ...") and are labelled with no topic.
- Coverage of live dev posts after `intel_classify_topics`: **616 of 2,635 = 23.4%** (posts with a hashtag at the same moment: 615 = 23.3%; 09's 25.5% was measured on 2026-11-05 on a different population). Rows by source: hashtag 426, inherited 170, lexicon 106, group 50. The lexicon adds little on dev because most posts are short seeded strings; two dev hashtags were left unmapped as ambiguous (`مشاريع` tags design portfolios here, `جيم` is a gym or a game), which removes their posts from hashtag coverage.
- `intel_seed_topics` on dev: 42 topics, 539 aliases; hashtags with >= 5 uses: 27 mapped, 11 unmapped with a reason, **0 uncurated**.

**Unit and API tests (criterion -> test).**

| Criterion | Evidence |
|---|---|
| Bucketing parity on % 100 with `flags.ts`; +/-1% over 100k on % 10000 | `test_bucketing.py` (4) |
| Assignment sticky; exposure once per (experiment, account) at first serve, no telemetry needed; bus exposure idempotent; chronological modes are not exposures | `test_experiments.py` (10), `test_exposure_at_assignment.py` (3) |
| `intel.config.published` on activate, rollback, start, stop; publish command; flag; payloads match the schemas; `discovery@1` parity | `test_experiments.py` |
| Every dev hashtag with >= 5 uses mapped or unmapped; run-time report; sensitive topics flagged; idempotent seed | `test_taxonomy_seed.py` (5) |
| Each classifier rule, Arabic normalization, inherited, cap 3, bus hook, page category read model, gold precision >= 0.8 | `test_classify.py` (7) |
| Tiers (half-lives), medium > long for a topic consumed only 8.5-10 days ago, emerging | `test_interest_tiers.py` (3) |
| Impression 0, like = weight x confidence, skip weak, decay, ineligible ignored, exactly once, late row in overlap, group join raises `group_cat`, skips personalization_off / before reset_at / synthetic, no double count of feedback | `test_aggregate.py` (7) |
| Decision 12 in the aggregator, feedback and the session vector; opt-out deletes inferred sensitive rows | `test_sensitive_inference.py` (3) |
| Migrations forward / backward; `mid_*`; polarity `muted` / `hidden` | `test_migrations_b2.py` (2) |
| Profile API: tiers, counts by event type, no item ids, delete suppresses, unmute / unhide, reporters never named, per account | `test_interest_api.py` (3) |
| Top topic up, disliked down under home@3; home@2c and home@1 unchanged; profile cache | `test_interest_ranking.py` (3) |
| Session vector: folds from the token without a read, impressions 0, dwell-only 0.3, hide -1.0, 20-min half-life, `min_events`, nothing under off, sensitive skipped | `test_session_interest.py` (4) |
| **Scenario D** under home@3: 4 cooking consumptions -> cooking on page 1 **3 -> 6** (>= +2), technology **14 of 20** (>= 30%); home@2c unchanged | `test_scenario_d_shift.py` |
| **Scenario A** under home@2b-r15 and home@3-r15: page 1 has 20 items, **100% recommended** (>= 60%), all eligible (blocked and minor authors absent) | `test_scenario_a_new_user.py` (2) |
| Cold start: `account.updated` read model (newest wins), language-matched page, onboarding rows / skip, onboarded topic leads | `test_cold_start.py` (4) |
| Intent: each rule fires; **golden: overlays at weight 0 give an identical order** (every intent); stored on the visit row | `test_intent_rules.py` (4) |
| Feedback: one transaction, repeat 200, exact undo, 404 for unknown / unserved / other's token / blocked, mute needs one of the item's topics, hide creator on a profile + event | `test_feedback.py` (5) |
| Effects +3 / +3 / -2 / -4 and -2 author; legacy test replaced; `reel.hidden` -> not interested | `test_feedback_effects.py` (6) |
| **Muted topic: 0 recommended items** with it (first page and later pages), undo restores; connected primary demoted not removed | `test_mute_topic.py` (3) |
| **Hidden creator: 0 recommended items**, followed connected post still present, `intel.creator.hidden` true / false | `test_hide_creator.py` |
| Integrity: once per cooldown, min accounts, below-rate and other reasons silent, flag off, schema | `test_integrity_flagged_event.py` (2) |
| New codes and **sensitive guard** (no history code without opt-in, sensitive topic never named, no group named) | `test_why_sensitive.py` (4) |
| Preferences body, subset PATCH, 409, undo, validation, old import path | `test_preferences.py` (13) |
| Debug consent 24 h, revoke, purge after 90 d | `test_debug_consent.py` (2) |
| One case per control and toggle: formats, discovery level (0 / 0.075 / 0.15 / 0.1995), trending and new_creators (E12), languages + other_languages, personalization_off (chronological, next page), suggestion toggles served | `test_preference_effects.py` (6) |
| **Reset**: two steps; 429 + Retry-After; 0 engagement rows across 3 weekly partitions, no inferred row, no affinity, 0 visit rows, 0 behavioural keys; explicit like / muted / hidden, follows, hides and item feedback kept; event; **page 1 equals the cold-start page of a twin with the same connections** | `test_reset_recommendations.py` (2) |
| **Decision 7**: off -> no `feed:si`, no row; on -> last 3 searches' topics only, no digest or text; personalization_off disables | `test_search_signal_optin.py` (3) |
| **personalization_off switch: 0 SQL rows, 0 Redis keys, no bus rows** afterwards (first page, next page, batch, bus like, hide) | `test_personalization_off_collection.py::test_switching_personalization_off_purges_and_then_stores_nothing` |
| Account deletion of every R4 table | `test_account_deletion.py::test_r4_tables_are_erased_with_the_account` |
| home@1 parity and the recent golden | `feed/tests/test_home_v1_parity.py`, `test_modes.py`, `test_home_v2.py`, `test_continuation.py`: green |

## Test counts

- `bash scripts/test-service.sh feed` on the final rebuilt image: **968 passed, 1 skipped, 0 failed** (R3 ended at 854 + 1; the skip is the known infra-file test). `makemigrations --check`: no changes detected.
- New test modules: 24 (above), plus additions to `test_personalization_off_collection.py`, `test_account_deletion.py`, `test_first_page_budget.py`.
- Adjusted to the new contracts: `feed/tests/test_hide_rank.py` (items gain `topics`; the legacy not-interested test replaced), `feed/tests/test_modes.py` (the full preferences body), `test_delivery_config.py` and `test_config_schema.py` (schema 5), `test_eligibility.py` (rule E12), `bench_ingest_with_ledger.py` (2 round trips: ledger + vector).
- `python scripts/smoke_test.py`: all checks passed. `uvx ruff@0.17.3 check .` and `format --check .` on `services/feed` and `libs/tara_common`: clean. `scripts/intel/check_deploy.sh`: ok. Dokploy size check: **76,168** (< 100,000; includes track B's entries).

## Migrations, events, env vars, routes

- **Migrations (additive, applied on dev):** `intel/0011_r4_interests_feedback` (13 new tables; `intel_user_preference.reset_at`, `search_signal`, `home_sections`; `intel_page_ref.category_norm`; all small or new tables, defaults), `intel/0012_r4_config` (`discovery@1` active; `home@3`, `home@3-r15`, `home@3-r30` drafts = versions 9, 10, 11 on dev; idempotent; the reverse removes the drafts and keeps the released `discovery@1`, which the immutability trigger protects).
- **Events produced by feed** (behind `INTEL_EMIT_R4_EVENTS`, default on, in the write transaction): `intel.config.published`, `intel.integrity.flagged`, `feed.recommendations.reset`, `intel.creator.hidden`, `intel.search_signal.changed`. **Consumed by feed:** `account.updated`, `intel.experiment.exposed`, `search.queried`, `reel.hidden` (verified registered in the running feed-consumer). Schemas for all eight R4 events are in `libs/tara_events`.
- **Env var:** exactly one, `INTEL_EMIT_R4_EVENTS=true`: `.env.example`, `.env_prod.example`, `docker-compose.dokploy.yml` (`*feed-intel-env` anchor), `infra/compose/docker-compose.yml` (`*feed-intel-env`), `scripts/gen-dokploy-env.sh`, `infra/k8s/overlays/feed/configmap.yaml`, `docs/deploy/DOKPLOY.md` (new "Tara Intelligence R4, feed" section with the seed / classify / publish steps).
- **Routes (all under the existing `/api/v1/feed` prefix, served by `feed`; traefik `PathPrefix(/api/v1/feed)`, nginx `location /api/v1/feed` -> `tara-feed`, the k8s ingress already cover them; nothing new reaches `feed-signals`):** `POST feed/feedback/`, `DELETE feed/feedback/{id}/`, `GET feed/topics/`, `GET/PATCH feed/preferences/`, `POST feed/preferences/undo/`, `GET/POST feed/preferences/profile/`, `DELETE feed/preferences/profile/{dim}/{key}/`, `POST feed/preferences/onboarding/`, `POST feed/preferences/reset/`, `POST/DELETE feed/preferences/debug-consent/`. `GET feed/` items (every mode) and peek items gain `topics` (<= 3); first pages gain `meta.personalization_off`.
- **Beat (verified):** `intel.rebuild_creator_quality` and `intel.purge_preference_logs` (nightly) in `CELERY_BEAT_SCHEDULE`, listed by the dev feed-relay (`worker -B`); Dokploy `feed-worker` (`worker -B`) and the k8s worker component (`-B`) pick them up with no compose change. `intel.reset_recommendations` runs on the default `feed.tasks` queue (no new queue).
- **On dev:** `intel_seed_topics` (42 topics, 539 aliases), `intel_classify_topics` (2,635 posts), `intel_config publish --surface discovery` (one event for track B's consumers). No experiment created or started.

## API contract as delivered

As specified, with these notes: a `PATCH feed/preferences/` with no field is 400 (the phase-2 contract); `POST feed/preferences/reset/` with a bad or expired token is 400; `hide_creator` on a profile requires an active, unblocked account that is not the caller; `feed/topics/` matches `q` against the slug and both labels (normalized).

**Final reason-code list** (`intel/why.py` `CODES`): `self`, `friend`, `follow`, `page_follow`, `group_member`, `rec_popular`, `rec_fresh`, `public_pool`, `favorite`, `interacted_author`, `demoted_feedback`, `shared_groups`, `conversation`, `rec_topic` (with `topic` slug), `rec_topic_sensitive`, and the 7 new ones `rec_community_popular`, `rec_similar_watched`, `new_since_visit`, `continue_watching`, `rec_new_activity`, `rec_adjacent_topic`, `rec_generic`. `continue_watching` is defined for the R6 Continue Watching section and is not emitted before it exists.

## Deviations and why

1. **reels@2 and video@2 are not built:** the reels and video rankers are 04 phase 5 surfaces scheduled for R6. `interest_rel` ships in `home@3*` only.
2. **No marketplace config is seeded:** no ranked marketplace surface exists; `intel.config.published` carries `marketplace` in its enum for later.
3. **post_stats extensions (6.3) are not built.** Changing the predictor's denominators (reach from impressions, save and completion counts) would change the inputs of every stored version, home@2c drafts included; it needs its own parity review. Open item.
4. **"Decayed affinity" is the `creator` dimension of `intel_user_interest`** (lazy decay, three tiers). The legacy `affinity` table keeps today's undecayed counts so home@1 parity holds; Reset deletes both.
5. **Tiers compare as rates (value / half-life).** The three accumulators take the same deltas, so a slower tier is always larger in raw value; 06's "medium > long" and "short / long >= 3" are only satisfiable as rates. Ranking uses 02's mix of raw values.
6. **The session-vector block is a top-level `session_interest` section** (06 §20 names `session.dwell_only_weight`), to leave R3's schema-4 `session` contract unchanged.
7. **Intent:** `browse_video` reads the share of decayed video/reel format mass (the vector keeps no sequence); `explore` never fires before an Explore entry exists (R6). Overlays ship at weight 0, so ranking is unchanged (golden).
8. **`topic_explore` has a weight but no producer** (no Discover topic page yet).
9. **Page categories reach topics only from `page.created` / `page.updated` after this release;** profile's intel export does not carry the category, so pages that never emit an update have no category topic until then (track B could add it to the export).
10. **personalization_off:** `for_you` is served from the chronological rows with the keyset cursor (later pages detect a non-ranked cursor); every bus and server signal row is gated, including blocks and reports (the block and report read models still update); the feedback service keeps only the protective explicit actions (mute, hide creator). The age-class memo key (safety data, WP 4b.14) is the one key that remains.
11. **Integrity rate denominator** is the post's fan-out reach (impressions are not aggregated per post yet).
12. **Experiment exposure is recorded on ranked `for_you` first pages only** (the experiment surface); chronological pages are not exposures.
13. **Ingest makes 2 Redis round trips** on a batch with consumption-grade events (the ledger and the vector), still p95 18.4 ms.
14. **E10 language default:** the account language applies only when an `account.updated` was received (none on dev yet); otherwise no language filter, as before.

## Open items

1. Scenario C (repeat rate 25.7% on first pages under home@3-r15) is unchanged from R3: the exposure values of the drafts are home@2c's (R3 open item 1, an owner or tuning decision).
2. post_stats extensions (deviation 3).
3. Page category in profile's intel export (deviation 9), for the classifier backfill.
4. The gold set was labelled by an agent; a human pass would confirm the 0.96 precision.
5. For the verifier: merge with track B's report into `results/r4.md`; run track B's e2e against the live endpoints (`GET /api/v1/feed/topics/` returns 200 on dev); decide whether to record the R4 harness run in `results/phase-04b.md`.
