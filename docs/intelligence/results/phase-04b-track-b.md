# Phase 4b, R1, Track B: post, search and web

Date: 2026-11-06. Branch `feat/web-social-platform`. Nothing is committed or pushed; the verifier merges this file into `phase-04b.md` and writes the work log.

Scope (09 §4 R1, §3 row 10; 07 row 4b.9 and the web part of 4b.6; 08 §9.4 search row and §3 display rules):

- **4b.9:** reels "seen last" and full video pages (services/post).
- **4b.20-B3:** search trending honesty fix (services/search and web).
- **4b.6, web part:** the "Suggested" label, the why codes and `caught_up_index` passed through.

## 1. Work packages done

### 4b.9 Reels seen-last (post)

- **Setting:** `services/post/config/settings.py:138` reads `REELS_SEEN_WINDOW_H` from env, default 72, clamped to 1..720. A garbage value falls back to the default. Phase 5 has no `intel.config.published` yet, so this env setting is the documented fallback.
- **Two-phase pager:** `services/post/reels/services.py:426` `seen_last_page`.
  - Phase 1 is the `for_you` candidates (the unchanged `feed_queryset`) with no `ReelView` in the window. Phase 2 is the watched ones. Both run in keyset order `(created_at, post_id)` descending.
  - The opaque cursor (base64url JSON, `services/post/posts/keyset.py`) carries `(phase, snapshot, created_at, post_id)`.
  - The **snapshot** is the first page's server time, and the window `[snapshot − window, snapshot)` is evaluated against it (`_seen_reel_ids`, `:399`). A view recorded between pages therefore cannot move a reel between phases, so the pager never repeats or skips one.
  - A page that fills exactly at the end of phase 1 continues into phase 2 only if phase 2 has rows.
  - A garbage cursor returns 400 `validation_error` (`_snapshot`, `:409`).
- **View:** `services/post/reels/views.py:95` routes only `tab=for_you` to the pager. `following` keeps `ReelPagination` and stays chronological (a clarification, as instructed). The response envelope is unchanged: `prev_cursor` is always `null` and `has_more` equals `next_cursor != null`.
- **Unchanged:** the author's own reels, blocked and muted authors, and "not interested" reels stay excluded in SQL. The per-item post visibility check (`ctx.visible`) still runs on every page.
- **Index:** no migration was needed. `EXPLAIN (ANALYZE)` on the dev DB for a viewer with 76 views in the window:
  - Both phases use `Bitmap Index Scan on reel_view_viewer_idx` for the seen subquery (phase 1 as a hashed anti-subplan, phase 2 as a semi-join).
  - `reel` is read by `reel_recent_idx` and `post` by `post_pkey`. There is **no** `Seq Scan on post`.
  - Execution took 0.41 ms and 0.52 ms.

### 4b.9 Full video pages (post)

- **Audience rule in SQL:** `services/post/posts/services.py:909` `_video_audience` uses the same predicate reels use: own posts, public, friends for friends and followers audiences, and followed for the followers audience.
  - Friends come from graph `friend_ids`. Follows come from the relationships batch over at most 50 recent followers-only video authors (or the single `author_id`).
  - Blocked accounts are excluded in SQL. `moderation_status=removed` is now also excluded in SQL.
  - With graph down, only public and own videos pass (fail closed).
- **Bounded over-fetch:** `services/post/posts/services.py:958` `video_page` makes at most `VIDEO_MAX_FETCHES = 3` fetches of `VIDEO_OVERFETCH × size` (2 × 20) candidates.
  - The per-item `visible_to_viewer` check (pages, blocks, relationships) runs on each fetched batch, never on an unpaged queryset.
  - The keyset cursor `(created_at, id)` points after the last candidate examined, so nothing is skipped or repeated.
- **Caller:** `services/post/posts/views.py:102`. `?type=video` returns the same envelope as before.

### 4b.20-B3 Search trending honesty fix

- **Settings** (`services/search/config/settings.py:125-127`), with no env vars:
  - `SEARCH_TRENDING_MIN_AUTHORS = 3`;
  - `SEARCH_TRENDING_COUNT_FLOORS = (20, 50, 100, 500, 1000, 5000, 10000)`;
  - `SEARCH_TRENDING_CACHE_S = 300`.

  `MODERATION_INTERNAL_URL` was added at `:118`, defaulting to `http://moderation:8000`. That var is already in the Dokploy common env.
- **Model:** `SearchAccountRestriction` (`services/search/searchsvc/models.py:161`, table `search_account_restriction`). Columns: `account_id` PK, `kind`, `active`, `case_id`, `event_at`.
- **Migration:** `searchsvc/migrations/0008_search_account_restriction.py` (CreateModel, additive). It was generated in the container.
- **Writer:** `services/search/searchsvc/restrictions.py:59` `set_restriction`, newest wins like feed's `readmodels.set_restriction`.
  - An older event is refused.
  - A reinstate seen first leaves an inactive tombstone, so its older restriction is refused when it is retried later.
  - Every change drops both trending cache keys at once and again on commit (`invalidate_trending`, `:45`).
- **Handlers** (`services/search/searchsvc/handlers.py`):
  - `@on_event("moderation.actioned")` (`:270`): `target_type=user` with `restrict`/`shadow` sets the restriction and `reinstate` lifts it. Other actions and targets are ignored.
  - Idempotency: the worker's `ProcessedEvent` wrapper, plus newest-wins for redeliveries.
  - `account.deleted` now also removes the row (`:263`).
- **Trending** (`services/search/searchsvc/history.py:150-200`):
  - `counted()` excludes `PublicPostHashtag` rows whose `author_id` is actively restricted, before counting;
  - `_compute()` applies `HAVING authors ≥ 3`, orders by authors desc, posts desc, tag, and limits to 10;
  - `trending()` caches per window in the search Redis cache and keeps answering, uncached, if the cache errors;
  - Response: `{"data":[{"tag", "posts_floor": int|null, "window": "day"|"week"}]}`. `posts_floor` is the largest floor ≤ posts, or null below 20. **`posts` and `authors` are gone.** An unknown window falls back to `week`, as before.
- **Backfill:** `searchsvc/management/commands/search_backfill_restrictions.py`, modelled on graph's command.
  - Reads moderation `/internal/v1/intel/export/restrictions/` as issuer `search`, audience `moderation-internal`, applying with the export's `as_of`.
  - After a complete scan, any active row that moderation no longer lists is swept to a reinstate at the scan's start time.
  - It prints counts only, never ids.
- **Moderation:** not touched. The export (`SearchExportView`) checks only the shared internal secret and audience `moderation-internal`, so the search caller is already allowed. The dev run below proves it.
- **Event contracts:** `docs/architecture/phase-0/04-event-contracts.md`, `moderation.actioned` row: Search was added as a consumer. There is no new schema.

### Web

- **Search service:** `src/services/search.ts` `TrendingTag` is now `{tag, posts_floor: number | null, window}`.
- **`TrendingList.vue`:**
  - A null floor shows no count line.
  - Otherwise it shows «+{n} منشور في آخر 24 ساعة» / "{n}+ posts in the last 24 h", or the 7-day form. `floorText` renders 1K, 5K and 10K, and `countLine` builds the line (`:24-32`).
  - The toggles now read «آخر 24 ساعة» / "Last 24 h" and «آخر 7 أيام» / "Last 7 days". The tag stays in `<bdi>`.
  - Keys are in `postsFeed.ar.ts:154-158` and `postsFeed.en.ts:153-157`. The old raw-count plural key `postsFeed.search.posts` was removed; no other user had it.
- **Other `TrendingTag` users:**
  - `GlobalSearch.vue` shows only the tag, so it is unaffected.
  - `SearchHome.vue` and `RightSidebar.vue` embed `TrendingList`.
  - `SearchView.vue` does not use trending.
- **4b.6 contract in `src/services/feed.ts`:**
  - `FeedReason` gains `"rec_popular" | "rec_fresh"`, plus `isSuggestedReason` (`:68`).
  - `meta.caught_up_index` is typed (`:18`) and passed through as `HydratedFeedPage.caughtUpIndex` (`:94`, `:177-182`, int or null).
  - `item.source` is still sent as the batch hint.
  - There is no caught-up UI, and `HomeView.vue` is untouched.
- **`PostCard.vue`:** a "Suggested" strip (`data-testid="post-suggested"`, `:647`) appears above the author line when `feedReason` starts with `rec_`. It uses brand tokens, a Sparkles icon in `accent-500`, logical spacing only, and `text-start`.
- **`WhyThisPost.vue`:** `rec_popular` and `rec_fresh` are added both as server factor codes and as the fallback (`:41-42`, `:80-83`). A suggestion is never explained as "you follow X".
- **i18n:** the new pair `src/i18n/suggested.ar.ts` / `suggested.en.ts` is wired into `ar.ts` and `en.ts` with 2 lines each.

## 2. Acceptance, measured

| Criterion | Evidence |
|---|---|
| Reel position 0 is never viewed in the window while an unviewed eligible reel exists | `test_position_zero_is_never_a_reel_watched_in_the_window`, over 3 opens with views recorded between them. **Dev:** 60 seeded viewers with views in the last 72 h. With the old order, position 0 was a watched reel for **2** of them. With the new pager it was **0**. |
| Watched reels ≤ 10% of the first 20 when ≥ 40 unviewed exist | Test with 60 reels, 20 watched and interleaved: **0** watched in the first 20. **Dev**, same 60 viewers: old order had 31 watched reels across their first 20 (max 20 for one viewer); the new order has **0**. |
| 5 pages with views between pages: 0 duplicates, 0 skips | `test_reels_pager.py`: 50 reels, 13 watched beforehand, and the viewer watches every served page. Result: 50 served, 50 unique, exact two-phase order. Views on reels not yet served also skip nothing. **Dev:** 6 heavy viewers each walked their full for_you feed: 141 served, 0 duplicates, page sizes 10. |
| `EXPLAIN` uses `reel_view_viewer_idx` and does not seq-scan `post` | Measured on dev (see §1); no index migration needed. |
| Video pages return 20 when ≥ 20 visible exist (today 13) | `test_video_page_full.py`: 30 hidden interleaved with 30 visible gives page 1 = 20 and page 2 = 10, with no overlap. **Dev**, 4 seeded viewers: new page 1 = **20**, page 2 = **20**, overlap 0. The old code returned **16** for the first page on today's data; the 13 in 07 is the earlier baseline. |
| Over-fetch is bounded | Test: 40 rows dropped by the Python check give a full page of 10 within 3 × 20. With 3 × 10 all dropped, the page is short (`[]`, `has_more=true`) rather than an unbounded scan. Continuing returns exactly the 30 visible, in order. |
| Trending: no tag with < 3 authors | `test_a_tag_needs_three_distinct_authors` (2 authors with 30 posts is absent, 3 is present). **Dev:** 92 day tags and 134 week tags with links; 32 reach ≥ 3 authors; the API returns 10 of those. |
| Restricted or shadowed authors don't count, and count again after reinstate | `test_restricted_authors_do_not_count_until_reinstated[restrict/shadow]`: a floor of 20 drops to null, then the tag disappears, then the floor returns to 20 after reinstate. |
| Out-of-order and redelivered events are ignored | `test_an_out_of_order_or_repeated_event_is_ignored` (a reinstate before the restrict, and an older reinstate after a shadow). |
| `posts_floor` is null at 19 and 20 at 20..49, with every boundary covered | 16 parametrized boundaries (0, 19, 20, 49, 50, 99, 100, 499, 500, 999, 1000, 4999, 5000, 9999, 10000, 2.5M), plus API checks at 19/20/49/50 and at 10,000 rows. |
| No `posts` or `authors` key in the response | Unit test, plus e2e against the live API for both windows (ar and en runs). |
| The handler invalidates the cache, and the cache is per window | `test_the_handler_invalidates_the_cached_answer` (both keys dropped, the on-commit callback runs), `test_the_answer_is_cached_per_window`, and `test_a_cache_outage_still_answers`. |
| The sidebar shows no count below 20 | Vitest `trendingList.spec.ts` (null shows no line; ar `dir=rtl`; toggles). E2E `search.spec.ts` "sidebar trending block shows only bucketed counts" in **ar and en**: every count line matches the floor pattern, no other text appears in the rows, "Today" / «اليوم» is absent, and axe reports no serious or critical violations. |
| Search binds `moderation.actioned` | RabbitMQ after recreating the containers: `tara.events → search.events` is bound to `moderation.actioned` and to `account.deleted`. |
| Backfill on dev | `search_backfill_restrictions` printed `listed 0, applied 0, swept 0, active 0`. Moderation dev has 32 user cases and **0** restrict/shadow actions, so 0 is the true count. The search caller was accepted (no 401). |

## 3. Tests

- **post:** `bash scripts/test-service.sh post` passed **607** tests, and `makemigrations --check` reports no changes.
  - 19 are new: `test_reels_seen_order.py` 9, `test_reels_pager.py` 5, `test_video_page_full.py` 5.
  - Existing reels and video visibility tests still pass, including `test_reels_stay_out_of_the_videos_list`, `test_graph_down_leaves_public_reels_only` and `test_muted_and_not_interested_leave_the_feeds`.
- **search:** `bash scripts/test-service.sh search` passed **148** tests, and `makemigrations --check` reports no changes.
  - 40 are new, in `test_trending_floor.py`.
  - `test_search_v2.py::test_trending_counts_distinct_authors_in_the_window` was updated to the new shape and the 3-author floor.
  - `test_page_posts.py` now reads raw counts through `history.counted()`.
  - `conftest.py` clears the cache per test.
- **Lint:** `uvx ruff@0.17.3 check` and `format --check` are clean on services/post and services/search.
- **Web:**
  - `npm run lint` and `npm run typecheck` are clean.
  - `npx vitest run`: **60 files, 828 tests passed**. New specs: `trendingList.spec.ts` 4, `postCardSuggested.spec.ts` 9. `whyThisPost.spec.ts` gained 2. `postsFeed.spec.ts` was updated to the new trending shape and toggle label.
  - `VITE_STORAGE_PROXY=true npm run build` passes.
- **E2E** on the preview at :4173, output under `scratchpad/pw-r1-b`: `search.spec.ts`, `reels.spec.ts`, `video.spec.ts` and `home-feed.spec.ts` gave **19 passed**. Two new search tests are included (ar and en).
- **Smoke:** `python scripts/smoke_test.py` reports all checks passed.
- **Recreated containers:** only `post`, `post-consumer`, `post-relay`, `search` and `search-indexer`. Migration 0008 is applied.

## 4. Migrations, events, env vars, routes

- **Migrations:**
  - search `0008_search_account_restriction` (new table, additive);
  - post: none (`EXPLAIN` already uses `reel_view_viewer_idx`).
- **Events:** no new event or schema. search now consumes `moderation.actioned`; it already consumed `account.deleted`, which now also clears the restriction row.
- **Env vars:** consumed `REELS_SEEN_WINDOW_H` (post). Track A wired it into `.env.example`, `.env_prod.example`, `docker-compose.dokploy.yml`, `scripts/gen-dokploy-env.sh` and the k8s post configmap; verified present, and the running post container reads 72. Search settings now read `MODERATION_INTERNAL_URL`, which already exists in the Dokploy common env; dev uses the default.
- **Routes:** none new. The `/api/v1/search/trending/` and `/api/v1/reels/` responses changed shape compatibly; `/api/v1/posts/?type=video` keeps its envelope.

## 5. Deviations and why

- **`following` tab:** stays chronological, with the plain DRF cursor (planner decision 4).
- **Fixed snapshot for the "seen" window:** the window is pinned to the snapshot in the cursor. 07 does not mention a snapshot. Without one, a reel served in phase 1 and then watched would come back in phase 2 as a duplicate, failing the "0 duplicates with views between pages" criterion. With the snapshot, a reel watched mid-scroll counts as watched from the next scroll on, as intended.
- **Invalid cursor:** answers 400 `validation_error` on `for_you` reels and video lists. DRF returned 404 "Invalid cursor"; a cursor is never a resource, and 400 matches the rest of the API. Old DRF cursors held by open tabs at deploy time get a 400 on their next "load more" (a reload starts a fresh list). Web recovery from that 400 was not verified.
- **Video followers-only:** these posts pass SQL only for authors whose follow is confirmed in one graph batch, covering the 50 most recent distinct followers-only video authors (the same bound reels use). A followers-only video from a followed author outside that set is no longer listed; before, it could be listed after a per-item graph call. This is fail-closed and bounded. See open item 3.
- **Video `moderation_status=removed`:** now excluded in SQL as well. It was already excluded by `is_visible`.
- **Raw counts for internal use:** `history.counted()` returns raw counts for internal callers and tests only. They are never serialized.
- **Search thresholds:** these are Django settings, not intel config (planner decision 3: search is not intel ranking code). This adds no env vars.

## 6. Open items

1. **Minors filter in search trending:** waits for the author age flag to reach search (09 §3 row 10, 06 E9b, decision 37). It is not built.
2. **Reels `following` tab:** unchanged, still newest first, with no seen-last ordering. Phase 5.1-B2 moves `for_you` ownership to feed; post's 4b.9 order stays as the fallback.
3. **Video followers-only bound:** see §5. If product wants every followed author's followers-only videos in the list, graph needs a "who do I follow" read (no such endpoint today).
4. **Phase-5 config:** `REELS_SEEN_WINDOW_H` should be replaced by the reels config `seen.window_h` from `intel.config.published` once phase 5 publishes it.
5. **Dev data for restrictions:** dev moderation holds no restrict or shadow decisions, so the backfill applied 0. Re-run `search_backfill_restrictions` once on each environment after deploy (prod included) before relying on the filter for decisions made before this release.
6. **Docs:** `docs/architecture/phase-0/03-api-contracts.md` does not describe the trending fields. It was not touched (outside the owned files); the verifier may add the new shape.
