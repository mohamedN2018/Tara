# Phase 2 results: event tracking

Date: 2026-11-05. Dev stack (Docker Desktop, Windows 11, i5-14600K), `feed_db` on the shared
`postgres:16-alpine`. Work packages: 2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 2.9 (feed side) and
2.10 (track A, feed backend); 2.6, 2.6b, 2.8 and the seed-script side of 2.9 (track B:
producers, web tracker and seed guard; summarised in "Track B" below). The last
section, "Verification", is the adversarial review of both tracks and its fixes.

## WP 2.0 baseline

Command: `bash scripts/intel/baseline.sh` (each backend suite through
`scripts/test-service.sh <svc>`, which runs `makemigrations --check` and then
`pytest -qq --create-db` in the dev-requirements image; web: `npx vitest run
src/__tests__/feed.spec.ts src/__tests__/homeFeed.spec.ts`). The script counts the outcome
characters of pytest's progress lines (the `-qq` run prints no summary line), lists every
failing id and exits non-zero on a failure not in `scripts/intel/known_failures.txt`.

| Suite | Before phase 2 (images as found) | After phase 2 | Failed / skipped | Wall time (after) |
|---|---|---|---|---|
| feed | 122 passed | 220 passed (122 feed + 98 intel) | 0 / 0 | 13 s |
| post | 526 passed | 565 passed (track B and the verifier added tests) | 0 / 0 | 53 s |
| graph | 95 passed | 95 passed | 0 / 0 | 16 s |
| profile | 186 passed | 186 passed | 0 / 0 | 12 s |
| marketplace | 142 passed | 142 passed | 0 / 0 | 11 s |
| identity | 411 passed | 411 passed | 0 / 0 | 33 s |
| moderation | 139 passed | 139 passed | 0 / 0 | 11 s |
| media | 186 passed | 194 passed (track B added tests) | 0 / 0 | 13 s |
| ads | 88 passed | 88 passed | 0 / 0 | 8 s |
| web vitest (2 files) | 28 passed | 28 passed | 0 / 0 | 9 s |

No failures, so `known_failures.txt` is empty. The plan's "feed (114 tests)" was already 122.
Wall times are the pytest run in an already built image (the derived `:test` image is cached).

### Outbox relay throughput (replaces the "about 100 events/s" estimate)

`intel/tests/bench_outbox_relay.py` (run explicitly; not collected by default): 10,000
synthetic `OutboxEvent` rows in the feed test database, drained by
`tara_events.outbox.publish_pending` (batches of 200, one `UPDATE` per row), routing key
`intel.bench.synthetic` (no binding, so no consumer receives them).

| Publisher | Throughput |
|---|---|
| Null publisher (database work only) | 2,467 to 2,784 events/s (two runs) |
| RabbitMQ (`KombuPublisher`, persistent, broker confirms) | **1,370 events/s** |

01 section 5 and 02 A5 now quote the measurement. It is shared by every event the service
emits, which still argues for telemetry's own batched path (A5).

## WP 2.1 `intel` app

`services/feed/intel/` (apps, models, ports, handlers, urls, views, origin, deletion, hot,
checks, readiness, metrics, signals/, ranking/), registered in `config/settings.py`
`INSTALLED_APPS` and `config/urls.py`. `intel.0001_initial` migrates on a clean database
(`--create-db` in every run above). Existing feed URLs are unchanged
(`intel/tests/test_app.py`); `consume_events` also imports `intel.handlers`.

## WP 2.2 partitions

- `intel_signal_event` (daily on `received_at`) and `intel_user_item_engagement` (weekly,
  Monday, on `first_at`) are created by `RunSQL` with partitions from yesterday to 7 days
  ahead; `intel_signal_batch` is a plain table.
- `intel/signals/partitions.py`: `make_partitions` (7 days ahead), `drop_expired`
  (`INTEL_SIGNAL_RETENTION_DAYS`, default 30, dev 90; `INTEL_ENGAGEMENT_RETENTION_DAYS`, 7
  to 30), `purge_batches` (48 h). Command `intel_make_partitions`; beat tasks
  `intel.maintain_partitions` and `intel.purge_signal_batches` run hourly (idempotent, so a
  beat restart never leaves a day without its partition). Writers also create today's
  partition if it is missing.
- Dev after migration: partitions `intel_signal_event_p20261104` to `_p20261112` exist.
- Tests: `test_partitions.py` (7: 7 days ahead, idempotent, drop past retention, dev retention
  keeps 60-day-old partitions, UTC bounds, 48 h batch purge, task and command).

## WP 2.3 ingestion

- `POST /api/v1/feed/signals/` (`intel/views.py`, `intel/signals/{serializers,validate,ingest,store}.py`),
  throttle scope `intel_signals` = 60/min per account, 413 over 32 KB, 400 over 50 events
  or for an unknown top-level field. Per event: unknown type, server-only type, bad item,
  unknown field, missing required field and the video rules drop that event only, counted
  in the answer and in `intel_signal_rejected_total{reason}`. `pos` is optional on
  `feed_impression` (Verification, fix 1).
- Serve tokens (`intel/ranking/serve_tokens.py`): binary, HMAC-SHA256 (truncated to 16 B)
  under `INTEL_SERVE_TOKEN_SECRET`, 24 h, 108 base64url characters for a Home item. Home
  items now carry `st` (`for_you`: `home@1`, absolute position, source = fan-out reason;
  chronological modes: no config version, no position).
- Live check through the dev edge as seed account u001: 5 `for_you` items with `st`, a batch
  of 5 impressions + 1 `post_like` answered `202 {accepted: 5, rejected: {server_only: 1}}`,
  the same batch again `{accepted: 0, duplicate: true}`; the rows are `attributed=true`,
  `surface=home`, `cfg_version=home@1`, positions 0 to 4, served by `feed-signals`.
- **Latency** (`intel/tests/bench_ingest.py`, 50 events per batch, 60 batches each):
  `ingest()` p50 14.1 ms, **p95 18.3 ms** (budget 30 ms); the whole request through DRF with
  RS256 JWT authentication in the test client: p50 19.3 ms, p95 37.1 ms.
- Tests: `test_signals_ingest.py` (22 cases), `test_serve_tokens.py` (10 cases).

## WP 2.4 `feed-signals`

- Dev compose: service `feed-signals` (same image, gunicorn, `RUN_MIGRATIONS=false`) and a
  Traefik router `PathPrefix(/api/v1/feed/signals)` with priority 200.
- Dokploy: `feed-signals` with the one merged block `environment: {<<: *feed-env,
  RUN_MIGRATIONS: "false"}`, alias `tara-feed-signals`; nginx edge
  `location /api/v1/feed/signals { client_max_body_size 64k; ... tara-feed-signals }` before
  `/api/v1/feed`.
- Kubernetes: `infra/k8s/overlays/feed/signals-deployment.yaml` (Deployment and Service
  `feed-signals`), ingress rule listed before `/api/v1/feed`.
- `bash scripts/intel/check_deploy.sh`: all 18 checks ok. Re-dumped Dokploy compose
  73,388 bytes base64 (was 69,558; limit used here 100,000, Dokploy's cap 131,072); nginx
  answers 413 to a 100 KB body and passes a 40 KB one to `tara-feed-signals`; Traefik sends
  signals to `feed-signals` and pages to `feed`; `feed-signals` has `RUN_MIGRATIONS=false`
  and no `[feed] migrate` line.

## WP 2.5 bus- and server-sourced signals

- `intel/handlers.py`: `post.reacted/unreacted`, `post.commented`, `comment.replied`,
  `post.shared`, `post.saved/unsaved`, `post.reported`, `user.followed/unfollowed`,
  `relationship.muted/unmuted`, `user.blocked/unblocked` give one `source=bus` row each.
- `feed/views.py`: hide, unhide, snooze and unsnooze write one `source=server` row in the
  request's transaction (a repeat hide or a reason change is not a new action; an undo with
  nothing to undo writes nothing).
- Tests: `test_bus_signals.py` (18: 15 event shapes delivered 3 times each give exactly one row),
  `test_menu_signals.py` (9: each menu action and its undo, plus "the action rolls back if the
  signal write fails").

## WP 2.7 hashtags

`feed/services.py::_snapshot` keeps `hashtags` (cleaned, sorted); edits update them;
`PostState.hashtags` (migration `feed.0008`) makes an edit processed before a retried
creation win. Non-public items keep ids only, as before. `intel_content_ref` itself is WP 3.1.
Tests: `test_content_ref.py` (5 cases).

## WP 2.9 synthetic separation (feed side)

- `intel_synthetic_account` (label `seed-*` gives `synthetic`, `test-*` gives `test`, checked
  by a database constraint). Rows from a registered account are stored with that origin only
  while `INTEL_ACCEPT_SYNTHETIC=true`; otherwise they are **not stored at all**.
- Readiness `intel_synthetic` fails when the table is non-empty and synthetic rows are not
  accepted; deploy checks `intel.E003` / `intel.E004` refuse either flag in production.
- `feed/handlers.py`: reactions, comments (created, replied, deleted, restored) and shares by a
  registered actor move no `post_stats`, `affinity`, `reaction_state` or `comment_state` row
  unless `INTEL_SYNTHETIC_IN_RANKING=true` (dev).
- Commands: `intel_register_synthetic` (ids or a seed manifest) and
  `intel_seed_synthetic_signals` (`--days`, `--scale`, `--replace`; refuses production,
  `INTEL_ACCEPT_SYNTHETIC=false` and backdating past retention).
- Dev: the 120 seed accounts of `.seed-state/manifest.json` are registered as
  `seed-tara-seed-v1`; `intel_seed_synthetic_signals --days 60` wrote 735 rows. Only that
  few: the seed content was posted in the last days, and no item is "seen" before it was
  posted, so the 60-day window holds no older content. 5 telemetry rows I had sent as u001
  before the registration were relabelled `synthetic`.
- Tests: `test_synthetic_origin.py` (11), `test_synthetic_actor_exclusion.py` (4).

## WP 2.10 deletion

`account.deleted` -> `intel/deletion.py::erase_account`: every `intel_*` table (the list must
cover every intel model; a test enforces it), including other viewers' rows that name the
account's profile or page, the account's `feed:rank:*` sessions (pre-v2 key and every
surface key) and `intel:prof`, and `ZREM` of its posts from every `intel:pool:*` key.
Tests: `test_account_deletion.py` (4, the pool case against a real Redis).

## Other runs

- `python scripts/smoke_test.py`: all checks passed (after recreating feed, feed-relay,
  feed-consumer and starting feed-signals).
- e2e against the preview (:4173): `feed-hide.spec.ts`, `home-feed.spec.ts` (ar and en):
  5 passed.
- `uvx ruff@0.17.3 check` and `format --check` on `services/feed` and `scripts/intel`: clean.

## Track B (producers, web tracker, seed guard)

- **WP 2.6 post events** (`services/post`): `post.reaction.changed` (D8, normal and
  race-loser paths, `posts/services.py::_change_reaction`); `post.saved` / `post.unsaved`
  behind `POST_EMIT_SAVE_EVENTS` (default on, owner decision 6; ids only, never the
  collection; only a new save of a post the saver may see; `save_item` / `unsave_item` /
  `saved.py::save_into` now atomic); `reel.hidden` / `reel.unhidden` only when the hide row
  is created or deleted; `reel.viewed` in the view transaction; `record_view` needs
  `watch_ms >= 1000` (D12: missing or shorter answers `counted: false`; negative,
  non-integer or over a day is 400); `reel.state.changed` from
  `reels/reconcile.py::_save_state` under a row lock (D15). 15 strict schemas in
  `libs/tara_events/tara_events/schemas/` (the 7 new events and the 8 D9 events).
- **WP 2.6b media**: `media_app/transcode.py::probe_fields` adds `has_audio` and `fps` from
  the stored probe (left out, never guessed, when absent); both optional in
  `media.processed.v1.json`; an event recorded before the change still validates.
- **WP 2.8 web tracker**: `frontend/web/src/lib/{signals,useImpression,videoSignals}.ts`;
  hooks in `PostCard.vue`, `VideoPlayer.vue`, `ReelPlayer.vue`, `ReelPager.vue`,
  `ReelsView.vue`, `HomeView.vue`, `ProfileView.vue`, `PageDetailView.vue` and
  `stores/auth.ts` (`resetSignals` on account change). Flush every 10 s, at 30 events and
  when the tab is hidden (fetch keepalive); 50 events and 32 KB per batch; 200 in memory;
  one impression and one open per (session, item); progress at most every 5 s;
  allow-listed fields only (never `cfg` or `variant`); a retried batch keeps its
  `batch_id`; nothing for signed-out viewers; `setPersonalizationOff(true)` clears the queue
  and silences the tracker (wired to the preference in WP 8.1).
- **WP 2.9 seed side**: `scripts/seed/seed_dataset.py::refuse_production` runs first
  (`TARA_ENV=production`, or `--api` on the production domain or a subdomain; no override).
  Synthetic registration goes through feed's `intel_register_synthetic` after the accounts
  phase, with the ids in `.seed-state/synthetic-accounts.json`; `--register-synthetic`
  registers existing accounts.
- Tests: post 38 new (6 files), media 8 (`test_processed_payload.py`), seed guard 11
  (`uvx --with pytest pytest scripts/seed/tests`), web vitest 20 (`signals.spec.ts`),
  e2e `intel-signals.spec.ts` (ar, en, reel).

## Verification (adversarial review of both tracks)

Every phase-2 acceptance criterion was re-checked against the code and by running it.

### Defects found and fixed

1. **Impressions off Home were silently dropped.** The server required `pos` on
   `feed_impression`, but a `PostCard` on a profile, group or search page (and a Home item
   added live from the top) has no feed position, so every such impression was rejected
   as `missing_field`. `pos` is now optional (`intel/signals/validate.py`, `REQUIRED`): a
   served item's position comes from its serve token, an unattributed one keeps the
   client position or none. The schema description is updated
   (`docs/intelligence/schemas/signals.batch.v1.json`). Test:
   `test_impression_without_position_is_kept`. Live: a seed account's batch with one served
   impression and one profile impression without `pos` answers `accepted: 2`.
2. **Synthetic rows could be stored as `real`.** `intel/origin.py` cached the whole
   `intel_synthetic_account` registry per process for 60 s. An account registered while a
   process held the cache was stored as `real` (and moved `post_stats` and `affinity`) for
   up to a minute in every other process. Lookups are now exact: one primary-key query for
   an unregistered account, and only positive answers are cached. Test:
   `test_a_new_registration_is_seen_at_once_without_a_cache_reset`.
3. **A rolled-back partition stayed "known".** `partitions.ensure` remembered a partition it
   had just created even when the surrounding transaction rolled back. After that, every
   write for that day in that process failed with "no partition". The partition is now
   remembered only `on_commit`. Test:
   `test_a_partition_created_in_a_rolled_back_transaction_is_not_remembered`.
4. **The k8s `feed-signals` Deployment was invalid.** The feed overlay's
   `patch-deployment.yaml` had a target without a name, so it appended an image-less `app`
   container to `feed-signals` (and to the consumer and the worker). The patch now targets
   `name: service` (`infra/k8s/overlays/feed/kustomization.yaml`).
   `scripts/intel/check_deploy.sh` now checks that every rendered feed Deployment has
   exactly one container with an image; it fails on the old overlay and passes now.
5. **There was no library-wide schema check.** Added
   `posts/tests/test_event_schemas.py::test_every_schema_in_the_library_is_a_valid_json_schema`:
   every file in `libs/tara_events/tara_events/schemas/` must be a valid schema for its
   dialect, with an `$id` that matches its file name.

### Checked and found sound

- **Authorization.** The signals endpoint writes only the caller's own rows. Attribution
  comes only from a serve token issued to the same account for the same item; forged,
  foreign and other-item tokens give `attributed=false`. Unattributed rows are flagged
  `INELIGIBLE_ITEM` (fail closed until WP 3.1). `post.saved` is emitted only for posts the
  saver may see. Reel views, hides and the `view` endpoint keep `get_reel`'s 404 for
  strangers. No read endpoint exposes anyone's signals.
- **Transactions.** Every new post event is emitted inside the write's `transaction.atomic`.
  Feed's menu signals are written in the request transaction (`ATOMIC_REQUESTS=True`; a
  failing signal write rolls the hide back, `test_menu_signals.py`). Bus rows are written
  once per event id (`ProcessedEvent`).
- **Synthetic separation.** Production pins `INTEL_ACCEPT_SYNTHETIC=false` and
  `INTEL_SYNTHETIC_IN_RANKING=false` (Dokploy, k8s). Deploy checks `intel.E003` and `E004`
  enforce it, readiness fails on a non-empty registry, and the seed script refuses
  production. Live dev: the rows seed accounts wrote during this review are all `synthetic`.
- **Home in every mode for seed accounts** (live through the dev edge, 3 seed accounts):
  `recent`, `for_you`, `favorites`, `following` and the default (`recent`, owner decision 5)
  answer 200 with 20 items (favorites: 0, none set). Every item has `st`, and page 2
  answers 200.
- **Thresholds.** The validation constants in `intel/signals/validate.py` define what is
  stored, not how anything ranks; no ranking weight exists yet (phase 4). `home@1` is the
  only config version stamped, and it names today's `feed/ranking.py`.
- **Wiring.** Every new env var is in `.env.example`, `.env_prod.example`, both compose
  files, `scripts/gen-dokploy-env.sh`, k8s and `docs/deploy/DOKPLOY.md`. The signals route is
  in the Traefik labels, `nginx.conf` (`tara-feed-signals`, 64 KB) and the k8s ingress. The
  Dokploy compose size is 73,388 (< 100,000).

### Runs after the fixes

| Check | Result |
|---|---|
| `scripts/test-service.sh feed` | 220 passed (217 + 3 new), `makemigrations --check` clean |
| `scripts/test-service.sh post` | 565 passed (564 + 1 new), `makemigrations --check` clean |
| `scripts/intel/baseline.sh` (all suites) | 0 unlisted failures: feed 220, post 565, graph 95, profile 186, marketplace 142, identity 411, moderation 139, media 194, ads 88, web (2 files) 28 |
| seed guard (`scripts/seed/tests`) | 11 passed |
| web `npm run lint`, `npm run typecheck` | clean |
| web `npx vitest run` | 800 passed (57 files) |
| e2e on :4173: `intel-signals`, `home-feed`, `feed-hide`, `reels`, `video` | 18 passed |
| `python scripts/smoke_test.py` | all checks passed |
| `bash scripts/intel/check_deploy.sh` | all checks ok |
| `uvx ruff@0.17.3 check` and `format --check` (feed, post, media, scripts) | clean |

### Deviations from the plan (both tracks, accepted)

- `pos` is optional on impressions (fix 1); 03 section 4.4 listed it as required.
- Track A:
  - Bad events are dropped one by one, not the whole batch.
  - Telemetry without a serve token is flagged ineligible except for the viewer's own profile.
  - A `play_index` column was added.
  - The wall-clock check allows 66 s of claimed watch time per session in any 60 s.
  - `event_type` has no CHECK constraint.
  - Rows from registered accounts are not stored at all when synthetic data is refused.
  - The partition job runs hourly.
  - Account deletion matches rows that name the account, not `author_id`.
  - Every Home mode returns `st`; only `for_you` carries `home@1` and a position.
  - The synthetic seed writes no completions, since there are no real durations before WP 3.1.
- Track B: `POST_EMIT_SAVE_EVENTS` defaults on (owner decision 6; feed's consumer ships in
  the same release). Reel views from a browser still running the old bundle (no
  `watch_ms`) stop counting until it reloads.

### Open items

- **The production deploy needs `INTEL_SERVE_TOKEN_SECRET`** in the Dokploy environment
  (`${INTEL_SERVE_TOKEN_SECRET:?}`). Without it the compose does not render. The local
  `.env_prod` does not have it yet.
- WP 3.1 adds the public-item check (`intel_content_ref`), video durations and the hashtag
  handler. Until then unattributed rows stay flagged and completions are not checked
  against the video length.
- Pools (WP 9.1) must also drop a post on `post.deleted`. Account deletion finds the
  account's posts from feed's fan-out rows, which the post service's own `post.deleted`
  events may already have removed. That lookup also scans `feed_item` without an
  `author_id` index, which is acceptable for a rare event.
- e2e and smoke-test accounts are not registered as `test-*`, so their dev rows are `real`
  (16 rows in dev now). Production never runs them.
- The 60-day synthetic seed wrote 735 rows because the seed content is only days old. The
  10x dataset for WP 9.1 and 13.1 needs older content.
- The other k8s overlays have the same unnamed `patch-deployment.yaml` target, which
  appends an image-less container to their consumer and worker Deployments. This is
  outside phase 2 and was not changed.
- Smaller gaps:
  - The k8s feed config has no `REDIS_HOT_URL`.
  - The personalization switch is wired in WP 8.1.
  - Feed does not yet consume `post.reaction.changed`, `reel.*` or the new media fields.
