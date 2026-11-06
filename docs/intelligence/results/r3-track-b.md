# R3 Track B: ingest side and web (exposure ledger, dwell, token v2, gate, aggregator, refresh)

Branch `feat/web-social-platform`, on top of `0f59b6e` (R2). Nothing committed or pushed. Track A's files (`intel/models.py`, migrations 0008-0010, the config, `feed/*`, `session_ctx.py`, `ranking/home|exposure_rank`) were consumed, never edited.

## WPs done

### B1. `feed_dwell` and the tab session (07 4b.2)
- Web tracker, `frontend/web/src/lib/signals.ts`:
  - `feed_dwell` type and `dwell_ms` field, sent on that type only (`:51`, `:290`). Dedupe is once per (session, item) (`:249`).
  - `sessionId`, `lastActivity` and the dedupe keys (newest 2,000) live in sessionStorage under `tara.signals.session.v1` (`restore` `:132`, `persistNow` `:149`). Writes are debounced 500 ms and flushed when the tab hides. A storage error falls back to memory.
  - `signalSessionId()` (`:204`) returns undefined with personalization off or signed out.
  - Turning personalization off or signing out deletes the stored session.
- `frontend/web/src/lib/useImpression.ts`: dwell is the time the R2 impression v2 rule is met, counted before and after the impression. One `feed_dwell` is sent per displayed card, when it leaves the viewport, the tab hides, or the card unmounts or is reused (`sendDwell` `:111`, `onBeforeUnmount` `:195`). A card that was never displayed sends nothing.
- Server:
  - `intel/signals/validate.py`: `feed_dwell` accepts post kinds and requires `dwell_ms` (`:53`, `:69`). `check_dwell` (`:137`) drops, and counts as `dwell_overclaim`, any dwell over 10 min or longer than the time since the serve token was issued (+5 s skew).
  - `serializers.py:83/109`: `dwell_ms` is an unknown field on other types.
  - `ingest.py:320`: a second dwell for the same item in one batch is dropped (`duplicate_dwell`).
  - The dwell is stored in `watch_ms`. The consumed threshold the card needed is stored in `duration_ms` (`ingest.py:219-235`).
- Schema `docs/intelligence/schemas/signals.batch.v1.json`: adds `feed_dwell` and `dwell_ms` (additive).

### B2. Serve token v2 and the ingest gate (07 4b.16)
- `intel/ranking/serve_tokens.py`:
  - `VERSION = 2`, `VERSIONS = {1, 2}` (`:50`). v2 appends fmt u8, topic_id u16 (0), length_bucket u8, an 8-byte author prefix and visit_ord u8 (`:187`, decoded at `:260`). Codes are append-only: `FORMATS` matches post's `Post.Type`.
  - v1 tokens still validate until they expire; their v2 claims read as None.
  - `stamp_home_items(..., visit_ord=None)` (`:324`): `fmt` and the bucket come from the item's serialized snapshot. An excerpt stripped for this viewer gives bucket 0. Buckets come from `exposure.length_buckets` (`:373`, `length_bucket` `:133`). Track A passes `visit_ord` (`feed/views.py`).
- `intel/signals/ingest.py:65-80`: the batch claim is a single statement. A CTE reads `NOT EXISTS (intel_user_preference … personalization_off)` and returns `(off, inserted)`, so the gate costs 0 extra queries.
- Under off, the batch returns 202 with `rejected.personalization_off = n` and writes nothing (`:256-262`).

### B3. Exposure ledger v0 (07 4b.3, 06 §5.1-5.2): new `services/feed/intel/exposure.py`
- **Codec.** 13-byte records: 8-byte item prefix, 4-byte epoch minute, then one byte = state (bits 0-1) + dwell-only (bit 2) + visit_ord (bits 3-7) (`encode_record` `:99`, `decode` `:115`).
  - Key: `ledger_key()` (`:64`) is the registered `hot.exposure_key` name for codec v1, so `forget_account` deletes it. A later codec would add a `:v{n}` suffix.
  - States are `STATE_*` (`:52-55`).
- **`fold(raw, current_visit_ord)`** (`:150`): the highest state wins; the latest minute is kept.
  - `exposures` = distinct visit_ords, capped at 2.
  - `in_visit` is true if any record is in the current visit.
  - `Fold` gains two defaulted fields (`dwell_only`, `visit_ord`), so the 4-field contract is unchanged.
- **Compaction** (`compact` `:195`): one record per item for the `cap` most recent items, with ties broken by append order. The "≥ 2 exposures" flag sits in **bit 31 of the minute word**, so the visit bits stay intact and `in_visit` is exact across compaction (see deviations).
- **One Lua script per batch** (`_APPEND_LUA` `:279`):
  - Reads `visit_ord` with `HGET feed:sess` (0 if absent) and stamps it on every record.
  - `APPEND` and `EXPIRE ttl_h`.
  - Only when `feed:sess` exists: `HSET last_activity_at` (only ever raised) and `HINCRBY dc/cc`.
  - If the append would take the log past `2 × cap × 13` bytes, it appends nothing and ingest compacts instead: `GET`, fold, then a length-guarded `SET` via `_SWAP_LUA` (`:307`), so a concurrent append is never lost.
  - The script has a `#!lua` shebang (see deviations).
- **Fail-soft.** Every refusal is counted in `intel_hot_write_failed_total{key="exp"}` (`_failed` `:329`). Ingest still returns 202 and the SQL rows commit. Scripts are always run on the calling client (`_script` `:316`).
- **States from events** (`ingest.py:206-235`):
  - `feed_impression`, `video_start`, `video_progress` → displayed.
  - `video_skip` → skipped.
  - `post_open`, `reel_view` → viewed.
  - `video_complete`, `video_rewatch` → consumed.
  - `feed_dwell` is classified by `exposure.*` thresholds, with the consumed threshold scaled by the token's length bucket (dwell-only).
  - `profile_visit` and non-post kinds → no record. Serving never writes anything (`retrieved` is never a state).
- Thresholds are read only through `exposure.thresholds()` (`:255`) from `config.for_surface("home")`.
- Minutes come from ingest's `now`, which follows `X-Tara-Test-Now` under the R1 guard.
- `append_records(viewer, records, cfg)` (`:387`) is the public helper for Track A's harness. `load()` (`:398`) is a one-`GET` fold.

### B4. Benchmark: `intel/tests/bench_ingest_with_ledger.py`, plus `bench_exposure_oom.py` against a real full Redis

### B5. Engagement aggregator v0 (07 4b.13): new `services/feed/intel/signals/aggregate.py`
- Finds the (viewer, item) pairs with events received in `(lo, hi]`, then recomputes each pair from all its retained events (`_sql` `:83`). It upserts on `(account_id, item_id, first_at)` and deletes a row whose `first_at` moved (`aggregate` `:162`). It is idempotent by construction.
- Natural-key dedupe:
  - impressions and opens: distinct sessions;
  - dwell: the longest report per (session, item);
  - completions: distinct (session, play).
- Fills only `intel_user_item_engagement`: impressions, opens, completions, `max_watch_ms`, `dwell_ms`, `state`, `consumed_dwell_only`, `last_displayed_at`, `visits` (distinct client sessions).
- Likes, comments, shares and saves (bus rows) count as consumption that is not dwell-only.
- Skips:
  - `personalization_off` accounts, including events stored before they turned it off;
  - events before `reset_at`, once the column exists (checked at runtime);
  - synthetic and test actors, unless `INTEL_SYNTHETIC_IN_RANKING`.
- Scheduling: `run()` (`:221`) keeps a watermark in the default cache with a 2-minute overlap. With no watermark it covers the whole retained range.
  - Beat task `intel.aggregate_engagement` (`intel/tasks.py:53`), settings beat line (`config/settings.py:149`).
- Wiring is verified, with no compose change needed:
  - dev `feed-relay` runs `worker -B` (`infra/compose/docker-compose.yml:628`);
  - Dokploy `feed-worker` runs `-B` (`docker-compose.dokploy.yml:858`);
  - k8s worker component runs `-B` (`infra/k8s/components/worker/worker-deployment.yaml:34`).
- `REDIS_HOT_URL` for feed-signals is present in all three:
  - dev compose `:672`;
  - Dokploy `x-feed-env` `:282`, shared by `feed-signals` `:964`;
  - k8s `overlays/feed/configmap.yaml:30` (db 6).
- Live on dev:
  - First beat run: 808 pairs in 0.46 s.
  - Later ticks: 5 to 7 pairs in about 0.04 s.
  - Ledger keys in redis-hot have TTL 129,522 s (≈ 36 h).

### B6. Web refresh, pill, pull (07 4b.8, 06 §6.1, 08 §7.6)
- `src/services/feed.ts`:
  - `FEED_ENTRIES` is now `nav, load, reload, return, pull` plus the legacy `open, refresh` (`:50`).
  - `FeedVisit` (`:32`), `meta.visit`, `refresh_after_s` and `auto_refetch_after_s` are typed. Malformed values are dropped (`visitFields` `:152`).
  - Peek: `ids`, `new_count_capped`, `since`.
  - `sid` and `entry` are sent on first pages only. `fallback` is now read on both paths.
- `src/lib/homeRefresh.ts`:
  - `decideReturn` (`:40`) and `createHomeRefresh` (`:80`): `activate`/`deactivate` for KeepAlive, and `listen` for `visibilitychange`.
  - `pageEntry` (`:49`) gives `load` or `reload` for the page load's first first page, then `nav`.
  - `retryAfterMs` (`:131`).
  - `REFRESH_DEFAULTS` (`:20`) is used only before the first answer. A test compares it with `defaults/home.json`.
- `src/lib/pullToRefresh.ts`: touch gesture at the top only (`attachPullToRefresh` `:25`, which also sets `overscroll-behavior-y: contain` while listening). `keepAnchor` (`:102`) keeps the card under the finger in place.
- `src/views/HomeView.vue`:
  - `load(initial, entry, {silent})` (`:232`) sends `entry` and `sid`. It applies the server's timers, visit and markers. It drops duplicate ids within a page.
  - On `page.fallback`, if fewer than 5 new items remain, it asks for one more page (`FALLBACK_REFILL_MIN` `:110`).
  - 429 on a first page: the existing retry card, one automatic retry after Retry-After, then manual only (`rateLimited` `:355`). A 429 on a peek blocks peeks until Retry-After.
  - The pill shows the peek's `new_count`, less any rows already in the list or by an author snoozed here (`addFromTop` `:602`). A push the current mode does not contain changes nothing.
  - Silent refetch: `entry=return`. Pull and the refresh control use `insertFresh("pull")` (`:641`): new items above, id-set dedupe.
  - Wiring: `revealPill` `:691`, `pullRefresh` `:710`, `refreshControl` `:726`, `refresher` `:883`.
  - For You reload position: `isRestorable` (`:857`). `src/lib/feedPosition.ts` gains `RESTORABLE_MODES`.
- New components:
  - `src/components/feed/NewPostsPill.vue`: zero-height sticky wrapper, so it never moves the cards. When capped it says "N or more" in words, never "+N".
  - A floating pull indicator (`HomeView.vue:1006`).
  - A refresh control (`:984`).

### B7. Divider and marker (07 4b.7 web)
- `src/components/feed/NewSinceDivider.vue` («جديد من آخر زيارة» / "New since your last visit").
- `CaughtUpMarker.vue` («انت كده شفت الجديد» / "You're all caught up").
- Placement is by post id, after server index `anchor_index` (`markerAfter` `:113`, template `:1036`, `:1106-1107`):
  - The divider shows only when `new_count ≥ min_to_show`.
  - The marker appears at `caught_up_index` (index 0 is before the first post). It is never placed directly above `FeedEndCard`.
- i18n pair `src/i18n/homeRefresh.{ar,en}.ts`, wired in `ar.ts` and `en.ts` with two lines each. The Arabic plural uses six forms.

## Acceptance, measured

| Item | Result |
|---|---|
| Ingest p95, 50-event batch (gate + 50 v2 token decodes + Lua call) | **14.1 / 15.0 / 17.9 ms** over three runs (p50 12.5-13.1 ms, max 35.8-41.3 ms), target ≤ 30 ms. Host: i5-14600K, Docker Desktop, Postgres and Redis in containers. A first run gave 19.5 ms. |
| Ledger size | **2,600 B** compacted for 200 items (≤ 2.6 KB). Largest ever stored while 1,000 items streamed in: **5,200 B** (limit 5,200). |
| Displayed item visible to `fold()` | max **36-47 ms** (≤ 1 s). |
| Redis round trips per batch | median **1**. A compaction batch uses 3: script, `GET`, guarded `SET`. |
| Retrieved items never get a state | `test_served_only_items_never_get_a_state`: a recent and a for_you first page leave **0 bytes**; only the impressed item appears. |
| Reload duplicate = 1 exposure | Codec test (×3 same visit → 1) and ingest test (two batches, same `visit_ord` → `exposures=1`; next visit → 2). |
| Fail-soft under OOM | Real full Redis (`bench_exposure_oom.py`, `maxmemory` below `used_memory`, `noeviction`): **202, 50/50 SQL rows, refusal counted +1, no ledger key**. Also a refusing client in `test_exposure_ingest.py`. |
| personalization_off | Batch with all 10 client types: **0** `intel_signal_event` rows, **0** `intel_signal_batch` rows, **0 Redis commands** (spy), keyspace byte-identical. The gate is the one claim statement (no other `intel_user_preference` query). The aggregator writes **0** rows. |
| One feed_dwell per (session, item); reload keeps the sid | Web: second dwell refused, reload keeps the sid and re-sends no impression (`signals.spec.ts`). Server: in-batch dedupe; the aggregator keeps one per (session, item). e2e `intel-signals` sees exactly one `feed_dwell` with `dwell_ms ≥ 1000`. |
| Aggregator idempotent | Same window, wider overlapping window, and two runs without a watermark all give identical rows (`test_aggregate_engagement.py`). |
| Pill count == peek new_count | e2e (ar, en): a friend posts via `apiAs`; after 11 min away while scrolled, pill `data-count` equals the last peek's `new_count` (held = 0). |
| New content mid-session → 0 reordering | e2e: rendered id order identical before and after; scroll Δ ≤ 2 px. |
| ≥ 10 min away → pill, list and scroll unchanged | e2e (Playwright clock + `visibilitychange`) and vitest. |
| ≥ 30 min at top → refreshed, no duplicate ids | e2e: `entry=return` request with `sid`; the new post is first; ids unique; no skeleton flash. |
| Pull-to-refresh anchor ±8 px, no duplicates | e2e mobile with touch: `entry=pull`; anchor card moved ≤ 8 px; new post above it; ids unique. |
| For You reload to the same card | e2e (ar, en): `entry=reload&mode=for_you`; same card ±1. |
| Slow network, page 2 failing once | e2e (400 ms RTT, 400 kbps; page 2 aborted until Retry): retry card shows, Retry loads it, 3 pages (50 cards), **0 duplicate ids**. **CLS 2.69-3.54: NOT met** (target 0.1). See open items. |
| Divider and marker, ar RTL and en | vitest (6 cases × 2 locales) and e2e (real rows, server `meta` indices set by route): order post, post, post, divider, marker; text, `direction`, axe clean. |

## Tests
- **Backend**
  - `bash scripts/test-service.sh feed`: rc 0, `makemigrations --check` "No changes detected", **840 passed, 1 skipped**.
  - Re-run on the final tree (Track A's latest edits included, source mounted, private test DB): **844 passed, 1 skipped**.
  - New: `test_exposure_codec.py` (13), `test_exposure_ingest.py` (9), `test_aggregate_engagement.py` (8), `test_personalization_off_collection.py` (3).
  - Additions: `test_signals_ingest.py` (+4), `test_serve_tokens.py` (+5).
  - Benches: `bench_ingest_with_ledger.py`, `bench_exposure_oom.py`.
- **Frontend** (`frontend/web`)
  - lint clean, typecheck clean, build OK (`VITE_STORAGE_PROXY=true`).
  - **vitest 943 in 72 files** (R2: 905 in 69).
  - New: `homeRefresh.spec.ts` (12), `newSinceDivider.spec.ts` (12), `pullToRefresh.spec.ts` (5).
  - Additions: `signals.spec.ts` (+9).
  - Updated for the R3 entry names and the refresh button: `homeFeed.spec.ts`, `feedPosition.spec.ts`, `feedSkeleton.spec.ts`.
- **e2e** on preview :4173, all passing on the final runs:
  - `home-refresh` 10;
  - `home-slow-network` 2;
  - `feed-delivery` and `home-feed` 13;
  - `home-modes` 3;
  - `intel-signals` 4.
  - `home-modes.spec.ts` and `intel-signals.spec.ts` were updated: count mode buttons with `aria-pressed`, and expect the new `feed_dwell`.
- **Other checks**
  - `uvx ruff@0.17.3 check .` and `format --check .`: clean (935 files).
  - `python scripts/smoke_test.py`: all checks passed.
  - Dokploy size check: 74,994 (< 100,000).

## Migrations, events, env vars, routes
- Migrations: none of mine. Track A's 0008, 0009 and 0010 were applied on dev when `feed` was recreated.
- Events: no outbox event. `feed_dwell` is a client signal.
- Env vars: none.
- Routes: none.
- Containers rebuilt and recreated: `tara/feed:dev`; `feed`, `feed-signals`, `feed-relay`. `feed` had to be recreated: the old server answers 400 to `entry=load|nav|pull`.

## Deviations and why
1. **Compaction flag in bit 31 of the minute word, not bit 7 of the state byte.** Bit 7 is a `visit_ord` bit (bits 3-7), so a flag there would break `in_visit` for visits ≥ 16. Bit 31 is never set by a real minute (it would first be reached in the year 6053). The byte keeps state and visit exact; `test_compaction_keeps_state_count_and_in_visit_with_high_visit_bits` covers this.
2. **Codec version in the key name.** v1 is the bare `hot.exposure_key` name. Track B cannot edit `hot.py`, and only the bare name is in `forget_account`. A future codec gets `:v{n}` and must be registered there.
3. **Lua with a `#!lua` shebang.** Measured on Redis 7.4: a script without a shebang that starts with a read (`HGET`) still writes past `maxmemory`. The shebang makes Redis refuse the whole script in OOM, so `noeviction` really bounds memory and the refusal is counted.
4. **The "N new posts" pill counts from `as_of`, not from `meta.visit.since`.** `as_of` is always later than `since`, and counting from the visit start would offer posts already on screen. Rows the list already holds, and rows by an author snoozed here, are subtracted, so the pill equals `new_count` when the list holds none of them (asserted in e2e).
5. **"Watch ≥ 30 s for long video" → consumed is not implemented.** There is no `exposure.*` config key for it, and ingest has no duration. `video_complete` and `video_rewatch` are consumed. Track A's schema needs a key such as `exposure.long_video_consumed_ms` first.
6. **Like, comment, share and save are consumed only in the durable table** (the aggregator, within 60 s), not in the 36 h hot ledger. Bus rows are written by `intel/handlers.py` (Track A's), which has no ledger call. `exposure.append_batch` / `append_records` is ready for that wiring.
7. **`feed_dwell` storage.** Dwell goes in `watch_ms`, and the needed consumed threshold in `duration_ms`. There is no new column: migrations belong to Track A.
8. **Cross-batch dwell dedupe** happens in the client and the aggregator, not with an ingest read (07 4b.16 allows no extra read).
9. **Next-page sentinel restructured** for layout stability: the observed element is a 1 px line and the wrapper uses `display: contents` (`data-testid="feed-more"`). R2's tests still find `feed-sentinel`.
10. **`frontend/web/src/lib/feedPosition.ts` edited** (not in my list) to let For You restore its position, which B6 requires. The R2 assertion "never kept for a ranked mode" was updated.
11. **Bus and server signal rows** (`store.insert_row` callers) are not gated by `personalization_off`. 4b.16 scopes the gate to ingest, and blocks and reports are safety data. The aggregator ignores those accounts anyway.

## Open items
1. **CLS on a slow network is 2.7-3.5** against a 0.1 target, so the acceptance item is not met. `home-slow-network.spec.ts` reports CLS without enforcing it (like R2's critical-JS budget); `E2E_CLS_DEBUG=1` prints each shift.
   - Sources measured: cards growing after they are drawn. These are the snapshot-to-live swap, the comment preview a `PostCard` loads on its own (`p-3`, `comment-preview` rows growing about 250 px), and media boxes. They move the next-page skeleton and later cards.
   - My sentinel fix removed the sentinel's own share.
   - The fix belongs in `PostCard` and `FeedCardSkeleton` (reserve the comment-preview and media heights, or make the snapshot card match the live height). Those files are outside this track.
2. **e2e and the throttle.** Specs that share account `a` (home-feed, home-modes, home-refresh) can exceed `first_page_per_min` = 30 when run back to back. `home-modes.spec.ts`' API-level peek test then gets a 429 (it passes when run alone). `home-refresh.spec.ts` waits for the quota (`awaitQuota`); the verifier should watch for 429s in combined runs.
3. **Divider after a real +3-day return.** `INTEL_TEST_CLOCK_ENABLED` is off in dev, so the e2e uses real rows with the server `meta` indices set by route interception (labelled in the spec). The server path is Track A's `test_new_since.py`.
4. Wire bus-sourced consumption into the hot ledger (deviation 6), and add a long-video consumed key (deviation 5).
5. The CRLF warnings on Track A's test files are not mine.
