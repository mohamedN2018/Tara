# Phase 4c (R2) results: progressive loading and delivery, web track (B)

Source of truth: [09 §4 R2](../09-unified-roadmap.md), [08 §7](../08-brief-3-addendum.md) (7.1, 7.4-7.13) and 08 §11.2 scenarios 1-4 and 14. Track A (feed, media, `tara_common`) reports its own numbers to the verifier; this file holds the web track's work and the perf harness output. Nothing here is committed or pushed by the track.

Measured on 2026-11-06 against the preview build (`VITE_STORAGE_PROXY=true npm run build`, served by the existing `vite preview` on :4173) with Track A's feed and media containers already recreated (`GET /api/v1/feed/delivery/` answers, `meta.delivery` reaches the web, page 1 has 10 items). The harness is `scripts/intel/feedperf.cjs`; its raw output is in "Harness output" below, and its JSON is in the scratchpad.

**Before.** No harness run on the pre-change build is possible without a second preview server (not allowed) or `git stash` (not allowed). "Before" is therefore the 08 §7.1 baseline (measured 2026-11-05), shown in brackets. One cold desktop run of this harness on the pre-change preview, done before the first change, agrees with it: first post 675 ms, first image 915 ms, 148 requests, 4.31 MB, 28 API calls and 362.6 KB of script transfer before the first post, 8 `/media/resolve/` calls, 20 items on page 1.

## Per-WP status (web track)

| WP | Status | Where |
|---|---|---|
| Delivery store (enables 4c.2-B3) | done | `src/lib/delivery.ts`: `SAFE_DEFAULTS` (equal to `services/feed/intel/config/defaults/{home,reels,video}.json`, asserted in `deliveryStore.spec.ts`), `applyDelivery` from `meta.delivery`, `loadDelivery()` once per session in the background, sessionStorage with try/catch, rail gate, `positionRules()` |
| 4c.1-B3 first paint | done | `services/feed.ts` `page(..., {entry, snapshots: true})` → `snapshotPage()` + `hydrateLive()`; `HomeView.vue` `applyHydration()` (same key, in place; omitted post removed), `components/feed/FeedCardSkeleton.vue` (content only when the server sent it; id-only snapshots stay text-free skeletons); rails held by `holdRails()` until the first card with content or `defer_rails_max_ms`; first card's first image `loading="eager" fetchpriority="high"` (`MediaGrid` `eager`, `PostCard` `eagerMedia`) |
| 4c.3-B3 prefetch | done | `HomeView.vue` `setupSentinel()` (rootMargin = `prefetch_root_margin_vp` × innerHeight) + `retargetPrefetchMark()` (card with `prefetch_remaining_items` after it), one request per (mode, cursor), `warmMedia()` (one batched resolve + low-priority thumbs for `media_warm_items`); `VideosView.vue` same with the `video` block; `ReelsView.vue` sends `limit` and keeps the pager's own trigger. **4c.3b (BFF) not done**: measure-only per the roadmap |
| 4c.4-B3 states | done | 3 card skeletons first load, 2 next page; retries `next_page_retries` with `next_page_backoff_ms` × 2^n and sentinel un/re-observe; `FeedRetryCard.vue` (no toast), `FeedEndCard.vue` (has_more false only; links to Explore `/search` and Reels; chevrons mirrored in RTL, circular retry arrow not mirrored); hidden cards unmounted with `v-if` (a PostCard stays mounted only while its hide request is in flight, so a refusal restores it as it was) |
| 4c.5-B3 images, client | done | `services/media.ts` cache keeps variants, size and `urls_expire_at` (TTL = expiry − 2 min; old servers 10 min), `resolveThumb`, `resolveSrcset`, `srcsetOf` (variants without a width are left out); `MediaGrid.vue` thumbs for 2+ tiles, srcset + sizes + width/height + aspect-ratio for one; `UserAvatar.vue` thumbs (`useMediaThumb`); `loading="lazy"` on `VideosRail.vue:70`, `ReelsRail.vue:80`; batch window = `media_resolve_window_ms` (`batchLoader` accepts a function) |
| 4c.6-B3 video policy | done | `lib/playbackCoordinator.ts` (`muted_single`, most visible ≥ `min_visible` for `min_visible_ms`, pause below `pause_below`, save-data / reduced-motion / `click`, unmute carried to the next autoplay only, viewer's pause respected); `VideoPlayer.vue` loads playback and poster only within `load_margin_vp`, prefers `poster_480_url`, parks to a poster beyond `unmount_beyond_vp` (hls.js destroyed), `preload="none"` kept |
| 4c.7-B3 virtualization | done | `content-visibility: auto; contain-intrinsic-size: auto 900px` on `[data-feed-item]`; after `virtualize_after_items`, cards beyond `keep_mounted_vp` become placeholders of their measured height and remount on approach (`setupVirtualization()`) |
| 4c.8-B3 web part | done | `lib/api.ts` in-flight map (`dedupKey`, a POST with a different body is not shared, each caller gets its own copy); `lib/feedPosition.ts` + `HomeView.vue` `onPageHide()` / `restore()` (chronological modes, `entry=reload`, at most 3 pages, `entry=open` otherwise) |
| 4c.9-B3 web part | done | `lib/useImpression.ts` (`meetsRule`, `impressionRule`, 21 thresholds, `idef` = `def_version`, v1 and `idef` 1 while the rule is unknown); `lib/signals.ts` `idef` field |
| 4c.10-B3 critical JS | partly: measured, split, **budget not met** | `perf-budget.json` (150, v1), `scripts/check-perf-budget.mjs`, `npm run perf:budget`, `vite.config.ts` `build.manifest`, CI step "Critical-JS budget" (`continue-on-error`, see below); dialogs and editors moved to `defineAsyncComponent` (PostCard: theater, reactions, shares, composer, audience, why, collections, share box, block dialog, comment list; CreatePostCard composer; SharedPostCard theater; StoriesRail viewer and create dialog; AppShell chat dock; AppNavbar notifications panel) |

## Critical JS: transfer or decoded?

The 357 KB of 08 §7.1 is the **transfer** size. On the pre-change build the critical set (entry + its static imports + the Home route and its static imports) is **352.4 KB gzip** (level 5, as nginx serves) / 299.0 KB brotli / **1,135.8 KB decoded**; the harness measured 362.6 KB of script transfer before the first post on the preview. After the splits: **313.6 KB gzip** / 265.9 KB brotli / 1,000.2 KB decoded (30 chunks); 336.2 KB of script transfer before the first post in the harness (the preview's own gzip).

**Why 150 KB is not met.** What is left: the entry chunk 125 KB gzip, of which about 251 KB decoded is the **ar and en message catalogues together** (both locales ship in the entry); vendor 50 KB (Vue runtime + axios); `vue` chunk 29 KB (vue-router, vue-i18n with its message compiler); the navbar's always-mounted menus and search 20 KB; icons 15 KB; PostCard 17.5 KB; AppShell 14 KB; Home 13 KB. The next steps, none of them in this track's files: load only the active locale (about 30 KB gzip; needs `i18n/index.ts` and `main.ts` to await the other locale), precompile messages and use the vue-i18n runtime build (about 5 KB), lazy navbar menus (ProfileMenu, MainMenu, MessengerDropdown, GlobalSearch, about 15 KB), `fetch` instead of axios (about 15 KB). Even all of them leave about 250 KB.

**Revised scenario-14 target (recorded, not hidden).** At 400 kbps one KB costs 8 / 400 = 0.02 s. 313.6 KB of critical JS is **6.3 s** of transfer alone before any RTT, so first post ≤ 6 s cannot hold with this JS. Measured weak-network first post p50 **12.2 s** [13.2 s]; `/feed/` done 12.0 s. The revised target is first post ≤ critical-JS transfer + 3 s of round trips (about 9.3 s at today's 313.6 KB; 6 s needs about 150 KB). Second cause found: on the weak profile the rails' 1.5 s maximum hold (`defer_rails_max_ms`) expires long before `/feed/` answers, so 23 API calls still run before the first post (8-9 on desktop and mobile). Raising `defer_rails_max_ms` is a config change (server-side, Track A / owner).

The CI step runs `npm run perf:budget` after the web build with `continue-on-error: true`: every run shows the measured size and a failing step, without blocking merges while the budget is known not to be met. The verifier or owner should remove `continue-on-error` once it is met.

## Virtualization choice

The simple IntersectionObserver version (placeholders of the measured height, one observer with a `keep_mounted_vp` margin) is used. It measured within every target after 5 batches (DOM 3,692 [11,883], 4 `<video>` [95], heap 13.2 MB [29.5]), so `@tanstack/vue-virtual` was not added (no new dependency).

## Acceptance (09 R2), measured vs target [baseline]

| Criterion | Target | Measured (p50 / p90) | |
|---|---|---|---|
| First post, desktop | ≤ 450 ms | **384** / 408 [726-762] | met |
| First post, mobile (4× CPU) | ≤ 450 ms | **692** / 712 [704, measured without CPU throttling] | not met |
| `for_you` first post | ≤ 700 ms | desktop **454** / 483; mobile **776** / 852 [1,223] | desktop met, mobile not |
| First image | ≤ 650 ms | desktop **571** / 593; mobile 1,682 [829] | desktop met, mobile not |
| First load bytes | ≤ 1.5 MB | desktop **2.37 MB**, mobile 1.98 MB [3.97] | not met (see below) |
| First load requests | ≤ 90 | desktop **123**, mobile 103 [152] | not met |
| API calls before first post | 1 | desktop **8** [28 in the pre-change run]: `/me/`, feature flags, calls config, profile, notification preferences (app boot, not rails), `/feed/`, then the parallel `/posts/batch/` and `/media/resolve/` | not met |
| Page 1 = `delivery.first_page_size` | 10 | **10** in every run [20] | met |
| `/media/resolve/` calls | ≤ 2 | desktop **4**, mobile 3-4 [9] | not met |
| No poster or playback request below 1 viewport | 0 | **0** players below the fold with a `<video>` or poster | met |
| Next page asked with ≥ 2 viewports left | ≥ 2 | min **2.95**, typically 3.2-6.6 [0.4] | met |
| 0 visible waits while scrolling | 0 | **0** | met |
| After 5 batches: DOM / `<video>` / heap / media | ≤ 6,000 / ≤ 6 / ≤ 22 MB / ≤ 4 MB | **3,692** / **4** / **13.2 MB** / **3.14 MB** desktop; 3,723-3,826 / 4 / 13.3-13.5 / 2.91-2.99 mobile | met |
| Duplicate ids, 6 UI pages, chronological modes | 0 | recent **0**/110, following **0**/102, friends **0**/110; favorites has no posts for this account (not measurable) | met |
| Reload returns to the same card ±1 | ±1 | **1 card** (5,612 px → 4,961 px); e2e ±1 passes in ar and en | met |
| Critical JS | ≤ 150 KB transfer | **313.6 KB** gzip [352.4] | not met; revised target above |
| Weak network first post | ≤ 6 s or revised | **12.2 s** [13.2] | revised target recorded |
| Recovery within 3 retries | yes | desktop recovered by itself in 4.2 s, weak in 8.9 s, no click | met |
| 0 repeat media transfers per key in its bucket | 0 | **0** in every scroll run | met |

**Why first-load bytes stay above 1.5 MB.** Media is 1.58 MB of the desktop first load, and 1.13 MB of it is six single images served as their **original file**: these assets were uploaded before `display_640` / `display_1280` existed, so they have no display variants and the client correctly falls back to the original (it never invents a size). Images with variants load 10-30 KB each. A backfill of display variants for existing images (media, Track A) is the fix; the web needs no change. Scripts are 344 KB and fonts 65 KB.

**Why `/media/resolve/` is 3-5 calls.** The snapshot cards' photos, the hydrated cards' photos, then the avatars once `/users/lookup/` has named the authors are three dependent rounds; a fourth comes from comment previews. The 20 ms window merges each round, but rounds that depend on earlier answers cannot be merged on the client. The BFF option (4c.3b, measure-only) is the way to fold them.

**Mobile timings.** The mobile profile is 4× CPU-throttled, as 09 requires; the 704 ms baseline of 08 §7.1 was not. Most of the 692 ms is script parse and execution of the 1 MB decoded critical JS under throttling, which is the 4c.10 problem above.

## Harness output

<!-- feedperf:after:start -->
Run `after` on 2026-11-06T00:03:18.930Z. Host: Intel(R) Core(TM) i5-14600K (20 logical), 63.7 GB RAM, Windows_NT 10.0.26300 (win32 x64), Docker 29.8.2, Node v24.19.0. Preview http://127.0.0.1:4173; one seeded account (rank 0 by feed rows). n = 10 cold runs per profile; p50 / p90. Numbers are host-specific.

| Profile | Mode | First post ms | First hydrated card ms | First image ms | Requests | Bytes | API before first post | Script KB before first post | /media/resolve/ | Feed items on page 1 | /feed/ done ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| desktop | recent | 384 / 408 | 437 / 464 | 571 / 593 | 123 / 124 | 2.37 / 2.37 MB | 8 / 8 | 336.2 / 336.2 | 4 / 4 | 10 / 10 | 360 / 383 |
| desktop | for_you | 454 / 483 | 526 / 564 | 644 / 703 | 125 / 125 | 2.38 / 2.39 MB | 9 / 9 | 336.2 / 336.2 | 5 / 5 | 10 / 10 | 440 / 468 |
| mobile | recent | 692 / 712 | 930 / 1090 | 1682 / 1734 | 103 / 104 | 1.98 / 1.98 MB | 9 / 9 | 336.2 / 336.2 | 3 / 4 | 10 / 10 | 624 / 636 |
| mobile | for_you | 776 / 852 | 1161 / 1235 | 1797 / 1918 | 106 / 106 | 2 / 2 MB | 9 / 9 | 336.2 / 336.2 | 4 / 4 | 10 / 10 | 695 / 784 |
| weak | recent | 12165 / 12240 | 16626 / 16723 | 29948 / 30038 | 141 / 141 | 1.69 / 1.69 MB | 23 / 23 | 336.2 / 336.2 | 10 / 10 | 10 / 10 | 12039 / 12120 |

Players below the first viewport with a <video> or poster requested at first load: max 0 over all runs.

| Profile | Next pages | Trigger: viewports left (all triggers) | Visible waits | DOM nodes | <video> mounted | Heap MB | Media MB | Media repeat transfers | Duplicate ids |
|---|---|---|---|---|---|---|---|---|---|
| desktop | 5 | 6.53, 5.7, 3.89, 3.33, 3.2 | 0 | 3692 | 4 | 13.2 | 3.14 | 0 | 0 |
| desktop | 5 | 6.51, 5.7, 3.89, 3.33, 3.2 | 0 | 3692 | 4 | 13.2 | 3.14 | 0 | 0 |
| desktop | 5 | 6.53, 5.7, 3.89, 3.33, 3.2 | 0 | 3692 | 4 | 13.2 | 3.14 | 0 | 0 |
| mobile | 5 | 5.32, 6.22, 3.14, 3.56, 3.44 | 0 | 3826 | 4 | 13.5 | 2.99 | 0 | 0 |
| mobile | 5 | 5.75, 6.64, 3.56, 2.95, 3.39 | 0 | 3723 | 4 | 13.3 | 2.91 | 0 | 0 |
| mobile | 5 | 5.74, 6.63, 3.55, 2.95, 3.39 | 0 | 3723 | 4 | 13.3 | 2.91 | 0 | 0 |

Forced next-page failure (desktop): 2 aborted, 4 attempts, recovered without a click: true in 4154 ms; retry card shown: false.
Forced next-page failure (weak): 2 aborted, 4 attempts, recovered without a click: true in 8869 ms; retry card shown: false.

Duplicates over up to 6 UI pages: recent 0 in 110 items / 6 pages; following 0 in 102 items / 6 pages; friends 0 in 110 items / 6 pages; favorites 0 in 0 items / 0 pages (no posts in this mode).

Reload at 5612 px: back at 4961 px, same card: false, distance 1 card(s).
<!-- feedperf:after:end -->
