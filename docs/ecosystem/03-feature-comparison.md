# Feature comparison: Tara vs QTech vs target

Status: draft for review · 2026-11-03 · Tara branch `feat/web-social-platform`

Audience: Tara engineers and the product owner (Mohammed).

This document compares three things for each of the 10 Tara modules:

- **Tara today**: what the Tara code on `feat/web-social-platform` does now.
- **QTech has**: what the QTech Django monolith (`Qtech_company`) already does. QTech is used as a read-only reference.
- **Target**: what the module design aims for.

For each feature it records a **reuse decision**: whether QTech's work gets reused, and how.

## How to read this

**Paths.** Paths in the *Tara today* and *Target* columns are relative to the Tara repo root (`services/`, `libs/`, `frontend/web/`, `infra/`, `scripts/`, `docs/`). Paths in the *QTech has* column are relative to the QTech repo root (`backend/`, `frontend/src/`, `frontend/public/`, `infra/livekit/`, `nginx/`).

**Reuse decisions.** The brief asks for four labels. This document adds two more (`keep`, `leave`) so that every row has an honest answer.

| Label | Meaning |
|---|---|
| take design | Copy the shape (model, API contract, state machine, UI layout) and rewrite it in Tara's stack. No QTech code is copied as-is. |
| take algorithm | Port a specific piece of logic, with the fixes listed in the row and new Tara tests. |
| build new | Tara builds or extends it itself. QTech has nothing useful, or Tara already has a better base. |
| defer | Not in this round. The reason is in the row. |
| keep | Tara already has it and no QTech input is needed. Small fixes may still apply. |
| leave | QTech has it, but Tara deliberately does not take it. |

**How claims were checked.** Every claim comes from two passes over the code:

1. An audit pass read the QTech and Tara code.
2. A verify pass re-read the cited files and corrected the audit.

Where the verify pass corrected a claim, this document uses the corrected version. The main corrections are listed in [Corrections from the verify pass](#corrections-from-the-verify-pass).

Nothing was run against QTech, and most QTech areas have no tests. The verify pass ran three read-only checks:

- It reproduced the profile list `FieldError` inside the running `tara-profile-1` container.
- It executed QTech's Arabic `_norm()` on sample strings.
- It ran QTech's money formatter in Node 24.

Items marked **(unverified)** were judged plausible but not confirmed.

**Constraint.** `docs/architecture/project-review-and-plan.md` §5.2 says "no new services". Every target in this document extends an existing service or adds a Django app inside one. New containers are allowed only as workers and consumers for existing services (including the `media-transcoder` ffmpeg worker), as backing infrastructure (a second Redis, `redis-hot`; the clamd `media-scanner`; the production observability stack), and as third-party infrastructure (LiveKit). The full list and memory budget are in [04-roadmap.md](04-roadmap.md) §16.

## At a glance

Effort figures are the sums of the milestone estimates in each module design. Overlaps between modules are not removed (for example, "post as Page" appears in Social, Professional and Profiles), so the grand total is an upper bound.

| # | Module | Tara today | What QTech contributes | Biggest gap | Design estimate (eng-days) |
|---|---|---|---|---|---|
| 1 | Social network | Strong core: posts, reactions, comments, shares, graph, search | Comment-threading rule, photo grid and theater, HEIC conversion, crawler previews, Arabic normalisation, events shape | Ranking, stories, groups, events, trending; several privacy leaks | ~52 |
| 2 | Marketplace | MVP listings with moderation hooks | Price semantics, filter chips and sort sheet, facet principle, view-count cooldown | Photo upload, reviews, orders; listings stuck in `pending_review` in production | ~36 |
| 3 | Video | Uploads accepted with no checks, no playback | Watch-time visibility clock, beacon clamps, poster guards | Transcoding, playback, everything video-specific | ~44 |
| 4 | Reels | Nothing | Gesture kit, pull-to-refresh, URL-backed sheets, telemetry clock | Everything | ~48 |
| 5 | Messenger | Solid DMs and groups, realtime gateway | Presence algorithm, LiveKit deployment, call client and call UI, read-pointer design | Calls, private attachments, edit/delete/forward, presence bugs | ~33 |
| 6 | Ads Manager | Phase-7 baseline: campaigns, review queue, serve tokens | Geo lookup, viewability clock, bot markers, CSV BOM | Payment verification, targeting, overspend and double-billing bugs | ~45 |
| 7 | Professional | Work and education entries only | ATS model shape, recruiter Kanban layout, applicant field stripping | Jobs, applications, CVs, company profiles | ~36 |
| 8 | User profiles | Profile, field privacy, Pages | Photo theater, soft-delete managers, photo-as-post idea | Handle changes, counts, tabs, lifecycle; a signup DLQ bug | ~27 |
| 9 | Notifications | In-app list, preferences, Web Push | Push subscription lifecycle, deep-link builder, inline actions, live list | Aggregation, deep links, push hygiene on shared browsers | ~20 |
| 10 | Administration & moderation | Roles, flags, basic case queue | Capability precedence, matrix editor, audit index set, monitor UX | Suspension API, evidence, appeals, reversal, statistics | ~46 |

## Module 1 – Social network

Owning services: `post`, `feed`, `graph`, `search`, plus `profile` for groups. Stories and events become Django apps inside `services/post`. Groups go inside `services/profile`.

| Feature | Tara today | QTech has | Target | Reuse decision |
|---|---|---|---|---|
| Home feed | Fan-out on write, chronological; `FeedItem.score` is always 0.0; one sponsored slot on page 1 (`services/feed/feed/services.py`). Bugs: `followers` posts do not reach friends who don't follow; the author can be dropped when recipients exceed `FANOUT_MAX_RECIPIENTS`; unfollowing removes a friend's items. | Pull model using `IN(...) OR ... DISTINCT` with page-number paging (`backend/social/views.py` `PostViewSet.get_queryset`). Does not scale. | "For you" (heuristic score) and "Latest" tabs; the three fan-out bugs fixed. For non-public items `/feed/` returns ids only, and content is fetched through `POST /api/v1/posts/batch/`, so a revoked viewer never sees a stale snapshot. | build new |
| Ranking and trending | Missing: no score, no trending endpoint. | Missing. | `PostStat`/`Affinity` read models in feed; `compute_trending` every 10 min requiring at least 5 distinct authors per tag; moderator blocklist; region scoping. | build new |
| Posts (text, image, link, poll) | Present in `services/post/posts/` with 4 audiences, polls and SSRF-safe link previews. Gaps: the 4-image limit exists only in `frontend/web/src/components/post/CreatePostCard.vue`, and `PostCreateSerializer.media_ids` is unbounded; `media_ids` are not checked for owner, kind or readiness; `edit_post` lets an author edit a moderator-removed post, which re-indexes it in search. | Posts with public/department/private/custom audiences and a free-text "feeling" (`backend/social/models.py`). | Cap at 10 images or 1 video; media validated through a media internal batch lookup; edits refused on removed posts; `type` derived on the server. | keep + build new |
| Video posts | Partial and unsafe. `type=video` is accepted. Media allows `video/mp4`/`video/webm` up to 200 MB with no signature check (`services/media/media_app/validation.py` `matches_signature` returns True), and `process_media` marks any such file READY. The SPA has no `<video>` element. | None; video media renders as `<img>`. | Progressive MP4/WebM with `ftyp`/EBML checks, an ffprobe duration cap and a poster from a dedicated ffmpeg worker. HLS waits for Module 3. | build new |
| Reactions | 7 types, one per account. The picker in `frontend/web/src/components/post/PostActions.vue` already has hover, long-press and `suppressClick`. No who-reacted list and no breakdown. | Who-reacted list (`PostViewSet.reactions`: unpaginated, no block filter); breakdown via a GROUP BY per post (N+1). | `GET /posts/<id>/reactions/?type=` (cursor, blocked users hidden); `PostReactionCount` table; breakdown included in `/posts/batch/`. | take design (the endpoint idea only) |
| Comments and replies | Flat cursor list with `parent_id`. `frontend/web/src/components/post/CommentList.vue` already folds it into two levels and shows "replied to X". The real defect: a reply whose parent is on another page renders as a root. No comment edit or delete; `comment_count` is never decremented; no comment reactions. | `parent` is always the thread root and `reply_to` is the comment being answered; re-parenting in `CommentViewSet.perform_create`; comment reactions. Bugs: `parent` is writable with no same-post check; `get_replies` is N+1. | Server-side flattening (`reply_to_id`), a paginated replies endpoint, edit/delete with count decrement, `CommentReaction`, a per-post `comment_policy`. | take algorithm (flattening rule) |
| Shares | Present: flattening to the root post; a share cannot widen the original's audience (`services/post/posts/services.py`). No who-shared list. | Quote-share with root flattening and a sharers list; sends the notification with the wrong verb (`MENTION`). | Add `GET /posts/<id>/shares/`. | keep + take design (the list) |
| Stories | Missing. | Missing. | `stories` app in `services/post`; story tray in feed; close-friends audience; URL-backed full-screen viewer. | build new |
| Friends, follows, blocks | Present in `services/graph`, with events. Lists are unpaginated and filtered in Python. `SocialFriendsView`, `SocialFollowersView` and `SocialMutualView` return ID lists to any caller with no privacy or block check. `block()` emits no `friendship.removed`. `CloseFriendRelation` has no API. | Directed `Follow` only; unpaginated follower lists; `followers_count` computed per row with COUNT. | Cursor-paginated, privacy-aware lists (mutual included); counts endpoint; close-friends API; batch relationship endpoint. | build new |
| Mentions | Present: resolved through profile `by-handle`; only sent to people who can see the post; max 10. | The `MENTION` verb exists, but nothing parses mentions. | Add a `mentions_from` privacy setting. | keep |
| Hashtags | Present, but `services/search/searchsvc/handlers.py` `on_post_created` indexes tags from every post, which leaks private tags. Tags added by an edit are never indexed, and hashtag search docs are never removed. | None. | Index tags only from public posts; a normalised `Hashtag.norm` column; purge docs on blocklisting or when the last post is deleted. | build new |
| Groups / communities | Missing (only Pages and group chats). | Only HR department and announcement chat channels. | `groups` app in `services/profile`; `GroupRef`/`GroupMembership` read models in post with a fail-closed sync fallback. Group and event posts get a non-public audience forced by the server (verify pass: blocker, otherwise private-group posts leak into search and trending). | build new |
| Events | Missing. | `Event` + `EventAttendance` with an RSVP toggle and GROUP BY counts (`backend/social/views.py` `EventViewSet`). `is_public` is stored but never enforced; RSVP status is not validated; the attendee list is unpaginated. | Events app in `services/post` (the verify pass suggests naming it `gatherings` so it does not clash with `events.py`); PUT/DELETE RSVP; capacity checked under a lock; invites; reminders. | take design (model shape and tabs only) |
| Suggested people | Mutual friends and search autocomplete only; `AccountRef.handle` is cached but never read. | First 10 not-followed profiles, no ranking. | Friends-of-friends suggestions with dismiss and a cache. Mutual-friend previews must respect hidden friend lists. | build new |
| Global search | `ILIKE '%q%'`, limit 50, no cursor, no Arabic normalisation; `page.updated` is not consumed. | `icontains` scans. | `pg_trgm` on normalised columns; keyset cursor; groups, events, hashtags. Whether trigram extraction works for Arabic on postgres:16-alpine is **(unverified)**. | take algorithm (Arabic normalisation) + build new |
| Saved items | Save, unsave and list work; one default `SavedCollection`; `save_item` checks neither existence nor visibility. | Bookmark toggle only. | Collections CRUD; existence and visibility checked on save. | build new |
| Reporting | The UI can report posts and listings only. The backend already accepts comment, message, page and user targets at `POST /api/v1/moderation/reports/file/`, and moderation already dedupes per reporter on open cases. | No reporting in the social module. | One `ReportDialog` with reason codes on every surface. No migration needed: `target_type` is a plain CharField. | build new |
| Privacy controls | Post audience, profile visibility, per-field privacy, blocks. | Profile field masking. `SocialProfileViewSet.posts` has an IDOR that returns private posts. | Close-friends audience, friend-request policy, list visibility, a discoverability flag (named `searchable` and owned by profile; [05](05-database-architecture.md) §5, decision 9); one visibility function per entity, covered by a test matrix. | build new (QTech is a lesson here, not a source) |
| Photo grid and viewer | `PostCard.vue` shows 1 or 2 columns and has no lightbox. | 1/2/3/4+ grid with a `+N` overlay and a URL-backed theater (`?view=<id>`, Back closes it, swipe, arrow keys, thumbnails) in `frontend/src/components/social/PostFeed.vue`. Gaps: swipe and arrows ignore RTL; a deep link reopens at image 0. `PhotoViewer.vue` is a single-image viewer, not this theater. | `MediaGrid.vue` + `MediaTheater.vue` in TypeScript, with the photo index in the URL and RTL-aware navigation. | take design |
| iPhone HEIC photos | Media rejects HEIC (`ALLOWED_MIME` has no `image/heic`). | `frontend/src/utils/heic.js`: lazy-loaded `heic2any`, converts to JPEG at quality 0.9. | `frontend/web/src/lib/heic.ts`, with the chunk excluded from the PWA `precache.json`. Value is medium, because iOS Safari usually converts on pick already. | take algorithm |
| Share previews (WhatsApp, Facebook) | None; crawlers get the empty SPA shell. | A User-Agent map with an internal rewrite in `frontend/nginx.conf`, plus `backend/cms/social.py`. Defects: JSON-LD not escaped for `<`; `og:url` built from the internal path; `throttle_classes = []`. | Crawler rewrite for public posts, events and profiles; escaped JSON-LD; signed og-image URLs (checking media visibility is not enough, because most Tara uploads are public). | take design |

## Module 2 – Marketplace

Owning service: `services/marketplace`, extended. New endpoints stay under `/api/v1/marketplace`, which nginx already routes.

| Feature | Tara today | QTech has | Target | Reuse decision |
|---|---|---|---|---|
| Listing lifecycle | 8-state machine in `services/marketplace/marketplace/services.py`; sellers can reserve, mark sold, archive. Gaps: no DELETE; media cannot be edited; `update_listing` allows edits to active and removed listings without re-review. | Product catalogue with an external `buy_url` (`backend/cms/models.py` `Product`). | Edits refused on removed listings; material edits re-reviewed; soft-delete DELETE; expiry and renew. | keep + build new |
| Pre-publication review | `publish_listing` moves a listing to `pending_review` when `MARKETPLACE_AUTO_APPROVE` is false. Production sets it to false (`scripts/gen-dokploy-env.sh`), but moderation never hears about pending listings, so they stay stuck. The `reject` branch in `apply_moderation` is dead code because moderation has no reject action. The code default for the flag is True. | None. | `listing.review.requested` event, consumed as a separate pre-review case kind ordered oldest first; `dismiss` on a pending listing counts as approve. | build new |
| Categories | Parent FK, but the filter matches the exact slug only; a single `name` field; 8 seeded slugs. | `ProjectCategory`, shared by projects and products; a catalogue-driven settings validator in `backend/cms/chrome.py`. | `name_ar`, icon, and a per-category `attribute_schema` inherited by child categories; the filter includes descendants. | take design (catalogue-driven form). The validator is rewritten: chrome.py drops unknown keys silently, has no number kind and no length caps. |
| Photos and video | `ListingMedia` is stored and shown in the detail gallery (`frontend/web/src/views/ListingDetailView.vue`), but `CreateListingModal.vue` always sends `media_ids: []` and nothing validates media. | `ProductImage` FileField gallery. | Uploader with HEIC conversion and reordering; up to 10 images plus 1 video; owner/kind/ready/public check; EXIF/GPS stripped before display. | build new |
| Price and currency | `Decimal(19,4)` NOT NULL with default 0, so "free" and "price on request" look the same; currency is free text, 3 chars; `formatPrice` uses `toLocaleString()` with no currency. | `price` null means "on request" and 0 means "free"; `sale_price`; `Currency` choices; ordering by `Coalesce(sale_price, price)` with unpriced items last (`backend/cms/views.py` `ProductViewSet`). | Three-state price; sale price enforced by a DB check; currency allowlist including BHD/OMR/JOD. Sort keys use a composite keyset on (key, id), because many equal keys break cursor paging after 1000 rows (verify pass). | take design |
| Price display | `toLocaleString()`. | `PriceTag.vue` + `utils/money.js`. Checked in Node 24: amounts with 3 decimals are rounded to 2 (12.125 KWD shows as "KWD 12.13"). | `PriceTag.vue` in TypeScript, with a formatter that uses each currency's real minor units. | take design (component); rewrite the formatter |
| Search, filters, sort | `icontains` on title and description; `?min_price=abc` or an empty value returns 500; the UI sends only `q` and `category`. | A `facets` endpoint with one dimension, whose counts include its own filter, so the chips collapse; `CategoryTolerantFilter` is one line. | A filter serializer (400 instead of 500); a normalised `search_text` with a trigram index, queried with `__contains` rather than `icontains` so the index is used; per-dimension facets that exclude their own filter; the `min_price`/`max_price` names kept as aliases. | take design (facet principle) + build new |
| Filter chips and sort sheet | None. | `FilterChip.vue` (`aria-pressed`) and `SortSheet.vue` (bottom sheet on touch, menu on desktop). Arabic is hard-coded and there is no focus trap. | TypeScript ports with i18n keys and `useFocusTrap`. | take design |
| Location discovery | Free-text `location`. | None. | `MarketplaceCity` table; coordinates rounded to 2 decimals; bounding box plus Haversine distance (postgres:16-alpine has no PostGIS). | build new |
| Condition | new / like_new / good / fair. | n/a | Add refurbished and for_parts; make condition optional per category. | keep |
| Seller profiles and business sellers | `SellerProfile` is created but never updated or exposed; `seller_id` is always a personal account. | None. | `Seller` entity (an individual or a Page); page-role checks; storefront page. Business sellers need trader disclosure fields, which need legal review. | build new |
| Ratings and reviews | Rating fields exist with no write path. | None. | Reviews allowed only with a `ReviewEligibility` row (a completed order, or a two-way inquiry); one per buyer per listing. | build new |
| Favorites | Works, but `list_saved` returns removed, rejected and pending listings and listings from blocked sellers. Saved reserved or sold items return 404 when opened. The detail page never loads the saved state. | None. | One `listing_visible_to(viewer)` function used everywhere; price-drop alerts. | build new |
| Comparisons | Missing. | None. | `GET /compare/?ids=` returning aligned attribute rows. | build new |
| Seller and buyer dashboards | `my-listings` only. | None. | Seller stats (views, saves, inquiries) and an inquiry inbox; buyer view of inquiries and orders. | build new |
| View counting | None. | Redis `SET NX EX` cooldown plus a daily aggregate (`backend/core/visitors.py`); QTech still writes to the DB on every hit. | Cooldown per viewer per listing; a Redis hash buffer flushed by Celery. | take algorithm (the cooldown only) |
| Direct seller messaging | A chat thread is created from `marketplace.contact.requested`, but no message is sent from either side: the UI sends none and `ContactView` ignores the body. Chat raises on blocked pairs, which ends in the DLQ. | Support inbox moving pending → open → closed, with a first-responder claim (`backend/chat/views.py`). | Forward the buyer's message; chat ignores the request quietly for blocked pairs; a `ListingInquiry` read model for response-time metrics. | take design (the state idea only; no code) |
| Reporting | `listing.reported` becomes a moderation case; removal is enforced. Reports on drafts are accepted, which reveals that a draft exists. | None. | Visibility check, reason codes, dedupe. | build new |
| Orders, payments, shipping | Missing. | Client invoices only, with no payment gateway (`backend/billing/`); the invoice number is assigned by an UPDATE after save, which can race. | Order foundation for cash and meetup sales: sequence-backed order numbers; stock reserved when the seller accepts. | build new (foundation); defer real payments and shipping |
| Share previews | None. | JSON-LD `Product` + `Offer` emitted only when a price exists (`backend/cms/social.py`). | Same, with escaped JSON-LD and a stable og:image route (presigned URLs expire after 900 s). | take design |

## Module 3 – Video (long-form)

Owning services: `post` (new `videos` app; `Video.id` equals `Post.id`) and `media` (new transcoder worker). `feed`, `search` and `notification` need small changes.

| Feature | Tara today | QTech has | Target | Reuse decision |
|---|---|---|---|---|
| Uploads | Presigned PUT in `services/media/media_app/services.py`, with one 200 MB cap for every kind. Problems: no signature check for video; `video/quicktime` (iPhone) not allowed; frontend uploads default to `public`; the presigned PUT can be reused after `complete()`; `MediaAsset.bytes` is the size the client declared. | No video pipeline (only `SiteSettings.hero_video`, a FileField). | `video/quicktime` plus magic bytes; per-kind caps on the real stored size; private by default; daily quota; multipart upload in a late milestone. | build new |
| Transcoding (HLS) | Missing. `services/media/Dockerfile` has no ffmpeg and the media worker is limited to 256 MB. | None. | `media-transcoder` container on queue `media.transcode` producing an HLS ladder from 240p to 720p. ffmpeg is hardened: protocol whitelist, forced demuxer, non-root, and an environment without `INTERNAL_JWT_SECRET`. | build new |
| Posters and thumbnails | Image thumbnail only, always recorded as 320×320 whatever the real shape. | `backend/core/images.py`: width ladder, no upscaling, EXIF transpose, 50 MP cap, atomic write. Its no-upscale test skips a rung equal to the source width; port it as `<`. | WebP posters at 320/640/1280 from 3 frames, with real dimensions stored. | take algorithm (the guards) |
| Title, description, category, tags | Post body and hashtags only. | None. | `Video` model with title, description, category and normalised tags. | build new |
| Likes, comments, shares | Reusable as-is because the video's id is the post's id. | None. | Reuse the post endpoints. Legacy `PATCH`/`DELETE /posts/<id>/` return 409 for video posts so the two rows cannot drift apart. | keep |
| View counters | None. | `backend/core/tracking.py` clamps untrusted beacons: opaque session id, dwell cap, event cap, never raises. | A view counts after 30 s or more of clamped watch time, once per viewer per day; owner and bot views excluded; ingestion writes to Redis only. | take algorithm |
| Watch-time beacons | None. | `frontend/src/composables/useVisitorTracking.js`: counts only visible time; flushes on `visibilitychange`; uses `pagehide` rather than `unload`; sends a JSON Blob so DRF accepts it. | `useWatchTracker.ts`: the clock runs only while the tab is visible and the video is playing; sends with `fetch` keepalive and the Bearer header, and uses `sendBeacon` only on `pagehide`. | take algorithm |
| Subscribe | Graph follow works; follow targets are not validated. | None. | Follower-count endpoint; subscriptions tab through an expression index on the feed snapshot's `type` (no new `post_type` column or table backfill; [05](05-database-architecture.md) §5, decision 15). | build new |
| Channels | Profile tabs are posts, photos and friends only. | None. | Videos tab on profiles and Pages. | build new |
| Playlists, history, saved videos | None. `SavedItem` accepts `video`, but feed saves use `post`, so one video can be saved twice. | None. | Playlist, watch-later and watch-history tables; one saved item type. | build new |
| Related and recommended | None (feed score is always 0). | None. | Heuristic trending score; related videos by normalised tag overlap. | build new (uses QTech's Arabic normalisation) |
| Analytics | None. | Metric definitions in `backend/core/session_analytics.py` (engaged time, bots excluded). Aggregation runs at request time, is super-admin only, and returns raw IPs. | Daily rollups, a retention curve, traffic sources; buckets with fewer than 10 viewers merged. Region data needs a trusted edge header, which nginx does not set today. | take design (the definitions only) |
| Creator dashboard | None. | None. | `/studio` pages. | build new |
| Storage and delivery | Private MinIO bucket, presigned GET valid 900 s, Range requests work through `/tara-media/`. Media signs URLs with the MinIO root credentials. | Local volume served by nginx `try_files`. | Token-authorised playlist endpoint; segment URLs presigned per time bucket; playback revoked when a video is removed. | build new |
| Share previews | None. | Crawler pattern (see Module 1). | `VideoObject` JSON-LD, escaped, for public published videos only. | take design |
| Live streaming | None. | QTech's LiveKit setup is for calls only (`infra/livekit/`). | Not part of this module. | defer |

## Module 4 – Reels (short vertical video)

Owning services: `post` (a `Reel` row and a `Sound` library), `media` (the Module 3 pipeline) and `feed` (distribution, telemetry, creator analytics).

| Feature | Tara today | QTech has | Target | Reuse decision |
|---|---|---|---|---|
| Vertical feed, snap scroll, autoplay | None: no reels route, no `<video>`. | None. | `ReelPager` keeping 3 slides mounted; muted autoplay with `playsinline`; keyboard navigation. | build new |
| Upload | Same path as video, with the Module 3 problems. | None. | 150 MB cap; iPhone HEVC HDR tone-mapped to SDR (needs a fixture test); metadata stripped. | build new |
| Sounds / music | None. `MediaVariant.Kind.WAVEFORM` exists but nothing writes it. | `VoiceMessage.vue` reduces audio to peak buckets in the browser. | Server-side 64-bucket waveform; original sounds copied into their own media asset; an admin-curated library with required licence metadata. | take algorithm (the normalisation formula only); defer a licensed catalogue |
| Captions | Post body only. | None. | Caption text plus WebVTT upload. | build new |
| Likes, comments, shares, saves | The post endpoints can be reused, but the signals can be inflated: `unreact()` emits nothing, shares are not deduped, and `save_item` accepts any UUID. | None. | Per-viewer engagement dedupe in feed; new `post.unreacted` and `post.unsaved` events. | keep + build new (fixes) |
| Follow creators | Graph follow. | None. | Following tab fed by a `FollowEdge` read model in feed. | keep |
| Recommendations | None. | None. | Heuristic "For you" v1 with diversity caps and exploration slots, compared offline against chronological order before switching. | build new |
| Creator analytics | None. | Visibility clock (see Module 3). | Per-reel retention and traffic sources, rolled up from a Redis stream. | take algorithm |
| Pull to refresh | None. | `frontend/src/mobile/components/PullToRefresh.vue` (resistance curve, axis lock). | TypeScript port armed on the pager container, not on `window.scrollY`. | take design |
| Horizontal swipe in RTL | None. | `frontend/src/mobile/composables/useSwipeBack.js`, an edge back-gesture that is aware of text direction. | Only its thresholds and the direction flip transfer. | take algorithm (constants only) |
| URL-backed sheets | None. | `pushedView` with `router.back()` in `PostFeed.vue`. | Comments and share sheets live in the query string, so Back closes them. | take design |
| Poster as the LCP image | None. | `frontend/src/components/ui/SmartImage.vue` contract (one eager high-priority image, the rest lazy). | `ReelPoster` as a real `<img>` under the video. | take design |
| Lazy loading and delivery | `mediaService.resolveUrl` makes one request per id and serves originals. | None. | Two MP4 renditions, chosen by `saveData` and connection type; a batch media endpoint. | build new |
| Moderation | Post report path only; media of removed posts can still be fetched. | None. | Removal makes the media private; moderators get a preview bypass. Protecting minors needs age data, which Tara does not store. | build new |
| Link previews | None. | Crawler pattern. | Poster via a 302 redirect only; no `og:video` stream, which would invite hotlinking. | take design |

## Module 5 – Messenger

Owning services: `chat` (extended), `realtime`, `media` and `notification`. LiveKit runs as infrastructure.

| Feature | Tara today | QTech has | Target | Reuse decision |
|---|---|---|---|---|
| 1:1 chats | Present, deduped by `dm_key`. Two concurrent first DMs can return a 500 (no IntegrityError catch). | `get_or_create_direct` with no unique constraint, which is worse. | Catch the IntegrityError; add message requests. | keep |
| Group chats | Present, with problems: `create_group` does not enforce `MAX_GROUP_MEMBERS` (257 members possible); re-added members keep their old state; new members can read the full history; removed members still receive typing frames. | Roles, soft leave, system messages; no guard for the last owner. | `visible_from` per member; membership re-checked on removal; consent required when a non-friend adds you. | take design (system messages, soft leave) |
| Realtime socket | Channels gateway with RS256 auth that closes the socket at token expiry. The token travels in `?token=`; the subprotocol fallback is broken. | Two sockets per user, token in the query string, membership never re-checked. | Token in `Sec-WebSocket-Protocol` (echoed back); per-socket frame rate limit. | keep |
| Presence | Written but never read. `ping` returns before refreshing, so presence expires after 60 s of idle; closing one tab marks the user offline; `is_online()` is never called (`services/realtime/realtime/presence.py`). | Redis ZSET heartbeat plus a `HINCRBY` per-socket ref-count and `last_seen` (`backend/core/realtime.py`). Its counter hash has no TTL and drifts after a crash; presence is broadcast to every user. | One self-expiring socket ZSET per account; `last_seen`; presence sent only to authorised peers who watch it; no global broadcast. | take algorithm |
| Typing | Relayed; the client drops its own echo; no throttle; no stop event. | Same idea, no throttle. | At most one frame per 2 s per conversation; `typing.stop`; not relayed after a block or removal. | keep + build new |
| Delivery ticks | None. | "Delivered" is inferred from the peer being online, which is misleading. | A server-side delivered pointer. | build new |
| Read receipts | `last_read_message_id` plus a `message.read` event. The pointer can move backwards, and `member_states` exposes every member's pointer over REST. | Pointer-based `read_by` and `peer_last_read` (`backend/chat/serializers.py`). | Monotonic integer `seq` pointers; group read events not fanned out to every member; read-receipt privacy applied to REST as well. | take design |
| Attachments | Images and voice notes work, but chat media is uploaded as `public`, so anyone holding the id can fetch it. A negative `duration_ms` returns 500. No video or file UI. | Local FileField served `AllowAny` and inline with the client's Content-Type; `/media/chat/` is public through nginx. | Private uploads with presigned URLs issued by chat; file-type allowlist with forced download; EXIF stripped. | build new |
| Voice waveform | `VoicePlayer.vue` has play/pause only. | `VoiceMessage.vue` decodes every voice note when it mounts. | Waveform computed on the server as a media variant. | take algorithm (bucket reduction) |
| Edit, delete, forward | The fields exist (`edited_at`, `deleted_at`, `Type.SHARE`) but there are no endpoints. Moderation removal emits no event. | Forward without attachments; edit with no time limit; soft delete that wipes content. | Edit within 15 min, with history; delete for me or for everyone, leaving a tombstone; forward copies the attachment rows; moderation removal can be reversed. | take design (semantics, with fixes) |
| Search | None. | `icontains`. | Arabic-normalised `body_norm` with a trigram index, limited to the caller's conversations. | take algorithm (normalisation) |
| Unread counters | Pointer only; the only badge counts notifications. | One COUNT per conversation (N+1). | Unread computed as `last_seq - read_seq`. | build new |
| Archive, pin conversation, clear for me | None. | `cleared_at` and per-member archive (`backend/chat/models.py`). | `archived_at`, `pinned_at`, `cleared_at`. | take design |
| Block and report | Blocks are mirrored from graph, but typing is not block-checked. There is no report endpoint, although moderation already consumes `message.reported`. | None. | `POST /api/v1/messages/<id>/report/` with an evidence snapshot; a block ends any live call. | build new |
| Message requests | None. | None. | Requests folder for non-friends, fed by a `FriendPair` read model built from graph events. | build new |
| Voice and video calls | None. The nginx `Permissions-Policy` sets `camera=()`. | LiveKit v1.8 Dokploy compose and runbook (`infra/livekit/`), a call-token endpoint, `frontend/src/composables/useLiveKitCall.js`, `frontend/src/components/chat/CallOverlay.vue`. Flaws: the room name comes from the client (room hijack), and `call.*` frames are relayed to any user id. | LiveKit service with webhooks and TURN over UDP; room names generated by the server; a `livekit-api` token for one room, valid 10 min; a TypeScript call store and overlay. | take design (infrastructure, client engine, UI); rewrite the token endpoint and signalling |
| P2P mesh fallback | None. | `useMeshCall.js`, with static TURN credentials compiled into the bundle. | Not used. | leave |
| Message notifications | One row per message per recipient. Attachment-only messages produce an empty body. Each message shows two toasts in `frontend/web/src/App.vue`. | Per-message `ChatNotification` rows (write amplification). | One notification per conversation, cleared by `message.read`. | build new |

## Module 6 – Ads Manager

Owning service: `services/ads`.

| Feature | Tara today | QTech has | Target | Reuse decision |
|---|---|---|---|---|
| Personal ad accounts | `AdvertiserAccount` is created automatically, even by `GET /api/v1/ads/campaigns/`; `billing_status` is never read. | None. | Explicit accounts with a currency and a timezone. | build new |
| Business ad accounts | None (`owner_account_id` is unique). | None. | Ad accounts tied to Pages, authorized only by the caller's current page role, never by `owner_account_id`. | build new |
| Campaign objectives | Free-text `objective`; campaigns go ACTIVE on creation. | None. | Validated objectives; draft → in_review → active. | build new |
| Ad sets | Create and list only. The UI defaults to `cpc 0.10` and `cpm 1.00` (`frontend/web/src/views/AdCampaignView.vue`), so every ad set made in the UI is billed both ways. | None. | One `billing_event` per ad set. | build new |
| Ad formats | In practice text only. `media_id` is not checked, and `SponsoredCard.vue` renders no media. | None. | Image ads, sponsored posts, promoted listings. Video and reels ads come after Modules 3–4. | build new; defer video and reels formats |
| Targeting | `AdSet.targeting` is stored but never evaluated; the edge provides no geo signal. | `backend/core/geo.py` (Cloudflare header precedence, MMDB hot reload) and `backend/core/management/commands/update_geoip.py` (download to a tmp file, validate, `os.replace`). The private-IP check runs before the Cloudflare header, so the precedence must be reordered. | Country (only behind a trusted proxy chain), language, explicitly chosen interests. Age targeting only behind a flag and a legal sign-off; minors excluded. | take algorithm (geo lookup) |
| Budgets | Lifetime budget only. The final event overspends. `cpm/1000` is rounded to 4 decimal places, so a CPM below 0.05 is never charged. | None. | Daily and lifetime budgets with pacing; accruals in integers or high precision. | build new |
| Scheduling | The fields exist but are not in the UI; nothing checks that the end is after the start. | None. | Validated schedule plus a job that completes ended campaigns. | build new |
| Approval workflow | The creative review queue works (`IsAdReviewer`), but a decided creative can be decided again, and the decision event carries no owner. | `backend/hr/approvals.py`, an N-step engine tied to HR (a design reference only). | Reason codes; two-step review for special categories; an approved creative keeps serving while its revision is reviewed. | build new |
| Pause and resume | PATCH on status with no state machine (draft → active is allowed). | None. | Explicit allowed transitions. | build new |
| Metrics and reports | `campaign_report` joins with two `Count(distinct=True)` calls, which multiplies rows. | Metric definitions only. | `AdStatsDaily` rollups, HyperLogLog reach, date ranges, CSV export. | build new |
| CSV export | None. | `backend/core/export.py` writes a UTF-8 BOM, with no formula guard and a raw filename. | BOM, a formula-injection guard, and an RFC 5987 filename. | take algorithm (the BOM) |
| Billing history and statements | `AdBudgetLedger` rows are written but never exposed. | `Invoice`/`InvoiceItem` shape. It rounds to 0.01, which conflicts with Tara's 4-decimal ledger, and its numbering can race. | Funding ledger, monthly statements, sequence-based statement numbers. | take design (statement shape) |
| Payment verification | None. This breaks the rule "no paid campaign without approval and payment verification". | None. | Prepaid balance with manually verified top-ups and separation of duties; nothing serves until verified. A real gateway comes later. | build new; defer the payment gateway |
| Fraud prevention | Serve tokens (`services/ads/ads/serve_tokens.py`). Gaps: the `pl` claim is signed but never checked; tokens are spent before the "is it running" check; raw viewer ids appear in Redis keys. | `BOT_MARKERS` list in `backend/core/attribution.py`. | Viewability gate; a click requires an impression; self-impressions are not billed; bot user agents stored as invalid. | take algorithm (the marker list) |
| Viewability | An impression is counted the first time the ad is 50 % visible, with no minimum time. | Visibility clock (`useVisitorTracking.js`). | `useAdViewability.ts` (at least 50 % visible for at least 1 s) plus server-side timing checks. | take algorithm |
| Viewer controls | None. | None. | "Why this ad", hide advertiser, report ad. | build new |
| Conversions | None. | UTM and click-id resolver, for inbound traffic only. | A `tara_cid` click id plus a conversions API keyed per advertiser. | build new |

## Module 7 – Professional (LinkedIn-like)

Owning service: `services/profile`, extended with a new `careers` app in the same database.

| Feature | Tara today | QTech has | Target | Reuse decision |
|---|---|---|---|---|
| Professional profile | `bio` and `intro` only; no headline, no open-to-work. | None (HR profile only). | Headline and open-to-work preferences. | build new |
| Experience and education | Create and delete only. `GET /api/v1/profile/me/work/` (also `/links/`) fails with a FieldError, reproduced read-only in the running `tara-profile-1` container: the default CursorPagination falls back to `-created_at`, a field these models do not have. | None. | PATCH; fixed ordering; a link to a company Page. | build new |
| Skills and endorsements | None. | Arabic `_norm()` in `backend/core/chatbot.py`, but it replaces every symbol with a space, so C, C# and C++ become the same skill. | Skill catalogue with a skill-specific normaliser that keeps `+ # . / -`; endorsements only between friends. | take algorithm (Arabic letter folding only) |
| Certifications | None. | None. | Certification CRUD; https credential URLs only. | build new |
| CV upload | Media supports private PDFs with a `%PDF-` check. However, `bytes` is the size the client declared, and `scan_status` is hard-coded to `clean`. | Resume as a FileField on local media. | Real stored size; 5 MB cap; check for PDF active content; recruiters get short-lived presigned URLs and every access is logged. | build new |
| Company profiles | Pages with member roles, but no company fields. Moderation accepts reports on pages but nothing enforces the outcome. | None. | `CompanyProfile`; verification by admins; a rename clears verification; a moderation consumer for pages. | build new |
| Company followers | Graph page follows are not validated; a block does not remove page follows; no counts. | None. | `PageFollower` read model that tolerates out-of-order events, or follower counts owned by graph. | build new |
| Job listings | None. | `JobOpening` (soft delete) and a public careers board (`backend/hr/careers.py`). | `careers.JobPosting` linked to a Page; expires after 60 days; trigram search. | take design |
| Applications | None. | `JobApplication` with an 8-value stage enum and a unique (job, candidate) pair. Corrections from the verify pass: stage can be changed through PATCH (the QTech UI does exactly that); the stage action allows any stage to any stage; an anonymous apply overwrites an existing candidate matched by email. | Authenticated, idempotent apply; stage changed only through `POST /stage/` against a transition table; consent stored with a version and a timestamp. | take design (model and stages) |
| Interviews and feedback | None. | `Interview` with a panel, and per-panelist `InterviewFeedback`. The rating has no constraint, and the panelist FK is `SET_NULL`, which breaks the uniqueness rule. | Same shape, with a CHECK for 1–5 and a non-null panelist. | take design |
| Recruiter dashboard | None. | `frontend/src/pages/app/modules/HrRecruitment.vue` stage-column layout. It changes stage through PATCH, leaves out `withdrawn`, and loads 200 applications at once. | TypeScript Kanban with paging per column; the card's stage is taken from the server's answer. | take design (layout only) |
| Applicant field privacy | n/a | Field stripping in `to_representation` and write-locking in `__init__` (`backend/hr/serializers.py`); its capability checks run per row (N+1). | Separate views of an application for the applicant, the recruiter, the analyst and the panelist. | take design |
| Capability map | Page roles only. | `backend/hr/permissions.py`: a global role, with a DB lookup on every call. | Page role → careers capability map; a new recruiter role. | take design (the idea only) |
| Activity log | None. | `TaskActivityLog` shape. | `ApplicationEvent` for stage changes and CV access. | take design |
| Professional posts | `Post.author_type=page` exists but no code creates such posts. | None. | Post as a Page (shared work with Modules 1 and 8). | build new |
| Connections | Graph friendships. | None. | Reuse friendships as connections. | keep |
| Employment verification | Free-text work entries. | None. | Only verified Pages may confirm employment, and never the person asking for it (verify pass: blocker). | build new |
| Saved jobs and alerts | None. `SavedItem.item_type` is a free CharField, so no migration is needed. | None. | Saved jobs; daily or weekly alert digests. | build new |
| HR, payroll, attendance, OKRs, tasks | n/a | Large HR domain in `backend/hr` and `backend/tasks`. | Not relevant to a social ecosystem. | leave |

## Module 8 – User profiles

Owning service: `services/profile`, with small changes in `graph`, `post`, `marketplace`, `search` and `media`.

| Feature | Tara today | QTech has | Target | Reuse decision |
|---|---|---|---|---|
| Avatar and cover | Set by PATCH with no check of owner, kind or status. The SPA shows full originals everywhere, because `frontend/web/src/services/media.ts` `resolveUrl` ignores variants. | Profile photos as hidden posts that can be liked (`Post.photo_kind`), but those posts are created inside a GET request. | Media validation; crop and HEIC conversion; the SPA uses thumbnail and preview variants; profile-photo posts created from an event, with the audience following the profile's visibility. | take design (the photo-as-post idea) |
| Display name | Identity allows 120 characters at signup but the profile column holds 80, so `ensure_profile` fails and `account.registered` ends in the DLQ: no profile is ever created. | n/a | Same limit on both sides, plus a regression test. | build new |
| Handle | Generated once, by default from the email local part, and never changeable. Handles requested at registration are not checked against reserved words. | None. | `HandleRegistry` shared by users and Pages; reserved-word list; 14-day cooldown; the old handle held and redirected for 30 days. | build new |
| Bio, intro, location | Present; `intro` has no length limit. | n/a | Length caps. | keep + build new |
| Website and social links | Generic links. The GET list fails (see Module 7). `URLField` also accepts `ftp://`. | n/a | Typed platforms with a host allowlist; max 10 links. | build new |
| Friends / followers / following | The SPA downloads 7 full lists. Friends of restricted profiles are still shown (`frontend/web/src/components/profile/ProfileFriendsTab.vue`). | Injects `followed_ids` into the serializer context, though other fields in that serializer are still N+1. | Graph summary endpoint, paginated lists, batch relationship flags. | build new |
| Posts tab | `?author_id=` filters by audience after paging, so pages can be short or empty. The profile lock is not enforced on the server. | IDOR in `SocialProfileViewSet.posts`. | `AuthorPrivacy` read model; audience filtered in SQL. | build new |
| Photos tab | Built from posts already loaded; shows originals; video files appear as `<img>`. | Theater in `PostFeed.vue`. | `GET /api/v1/posts/media/` plus the shared viewer. | take design |
| Videos and reels tabs | None. | None. | Added once Modules 3 and 4 exist: roadmap milestones 5.7 (Videos tab) and 5.8 (Reels tab). | build new (in step 5) |
| Listings tab | No `seller_id` filter. | None. | `?seller_id=`. | build new |
| Professional info | Work and education create/delete only. | n/a | See Module 7. | build new |
| Activity history | None. | None. | Event-fed log of the user's own activity (ids only), on a separate consumer queue, kept 365 days. | build new |
| Privacy settings | Profile visibility plus 7 field keys. `visibility=custom` is accepted. | Field masking by role. | List visibility, friend-request policy (owned by graph, per the verify pass), "searchable" flag. | build new |
| Profile types | Personal profiles implicit; Pages partial. | None. | Creator type; page avatar/cover API; `page.updated` event. | build new |
| Lifecycle: deactivate, delete, takedown | `deleted_at` is never set; no events. | Soft-delete manager pair in `backend/accounts/managers.py`. | Deactivation (reversible) kept separate from deletion (anonymises); moderation hides fields reversibly. Set both `default_manager_name` and `base_manager_name`. | take design (the manager pair) |
| Image safety | `_thumbnail` already calls `exif_transpose`, and `Image.thumbnail` never upscales. | `images.py` guards. | Only the pixel cap is new; worker memory limits matter more. | take algorithm (pixel cap) |
| Link previews | None. | Crawler pattern. | Opt-in privacy setting; og:image on a public cached path (an nginx `internal` location cannot serve crawlers). | take design |

## Module 9 – Notifications

Owning service: `services/notification`. Producers (`chat`, `graph`, `marketplace`, `ads`) only add event fields; `services/realtime` gets two bridge handlers.

| Feature | Tara today | QTech has | Target | Reuse decision |
|---|---|---|---|---|
| Friend requests | `friend.request` and `friend.accepted` kinds, with no `subject_ref`. A withdrawn request emits nothing. | Inline approve/reject buttons in `frontend/src/components/social/NotificationBell.vue`; the resolved state lives only in the client. | Inline Accept/Decline with the resolution stored on the server; new `friendship.request.withdrawn` event. The root of `NotificationItem.vue` is a `<button>`, so the row must be restructured first. | take design |
| Likes and reactions | One row per reactor; no aggregation; `unreact` emits nothing. | None. | One aggregated row per post, counting distinct actors. | build new |
| Comments, replies, mentions, shares, follows | Present (`services/notification/notifications/handlers.py`). | n/a | Store `target_ref` for deep links. | keep |
| Messages | One row per message per recipient; attachment-only messages produce an empty body; two toasts per message in `frontend/web/src/App.vue`. | Per-message rows. | One row per conversation, cleared by `message.read`. | build new |
| Marketplace | `listing.status` is sent to the seller for their own actions, because the handler passes no `actor_id`. | None. | A `source` field on the event; inquiry notifications. | build new |
| Ads | `ad.review.decided` has no consumer and carries no owner. | None. | Review and budget notifications, once ads adds owner fields. | build new |
| Orders and professional | No producers exist. | None. | Added with those domains: `order.*` events and notification kinds in roadmap 4.10; job and application notifications in step 7. | build new (in steps 4 and 7) |
| In-app list, unread count, mark read | Present. `ReadSerializer.ids` has no size cap. | A shared list with upsert by id (`frontend/src/composables/useNotifications.js`); its unread count only covers loaded items. | A live Pinia list with dedupe; ids capped at 100. | take design |
| Deep links | Clicking an item only marks it read. The service worker drops `?query` and `#hash`. | `socialUrl()` builds a link per notification type. | URL built on the server from a kind registry; the service worker keeps search and hash. | take design |
| Grouping | None. | None. | Partial unique aggregate index. Expired aggregates must be closed explicitly, or new rows violate the index (verify pass: blocker). | build new |
| Web Push | Works when VAPID keys are set. Logout never unregisters, nothing re-binds on login, and retries resend to devices that already received the push. | `frontend/src/mobile/push.js` lifecycle: asks permission only on a user gesture, resumes on boot, unsubscribes locally before telling the server. | Local unsubscribe on every logout path; resume on login; one delivery task per device token. | take algorithm |
| Service-worker options | ar/en text for 10 kinds. | `frontend/public/sw.js` call options (4 keys); `dir:'rtl'` hard-coded for everyone. | Direction and language taken from the user's locale; no OS notification while a Tara window has focus. | take design (option keys) |
| Native push | Device tokens are stored but never delivered to, and any account can take over a token. | None. | Gate token registration until native apps exist. | defer |
| Email | None. | "Email only when offline" rule in `backend/chat/tasks.py`, but one email lists every recipient, which leaks addresses. | Per-recipient digest, verified emails only, one-click unsubscribe via POST. | take design (the rule only) |
| Preferences | Per-kind in-app/push flags. PATCH replaces the whole map, and nothing is validated. | Prefix muting (`backend/notifications/services.py`); muting only affects the socket toast. | Lookup order kind registry → category → default; PATCH merges. | build new |
| Quiet hours | Pushes inside the window are dropped. | None. | Pushes deferred and summarised when the window ends. | build new |
| Sound | None. | `frontend/src/utils/sound.js`, a Web Audio ping. | TypeScript port. | take algorithm |
| Skip push when the user is online | Presence is broken (see Module 5). | ZSET presence. | Added after the Module 5 presence fix. | defer |

## Module 10 – Administration & moderation

Owning services, split by bounded context:

- `identity`: account standing, capabilities, security events.
- `moderation`: cases, evidence, appeals, policies, blocklists.
- `admin`: console API, unified audit, statistics, settings, flags, health.

Enforcement stays in each service that owns the data.

| Feature | Tara today | QTech has | Target | Reuse decision |
|---|---|---|---|---|
| User management | No admin API. Only Django admin, and nginx does not route `/admin` in production (it falls through to the SPA). | `UserViewSet` lifecycle actions (`backend/accounts/views.py`). The hierarchy guard only protects super-admins, and suspend only flips `is_active`. | User list, detail, suspend, restrict and reinstate through an identity internal API. | take design (action set and guard idea) |
| Suspensions | `Account.Status.SUSPENDED` blocks login and refresh, but production has no way to set it. In `services/identity/identity/admin.py`, `AccountAdmin` lets staff edit `status` and `is_superuser` freely. | Suspend without revoking sessions. | `AccountRestriction` with reason, end date and actor; sessions revoked in the same transaction; `account.suspended` event; an appeal-only token. | build new |
| Feature restrictions | The `restrict` and `shadow` actions are not enforced anywhere. | None. | A `restr` claim plus a `NotRestricted` permission on write views. | build new |
| Page management | `Page.Status.SUSPENDED` cannot be reached; no events. | None. | Page suspend and reinstate; `page.status.changed` event. | build new |
| Marketplace moderation | The code default is `MARKETPLACE_AUTO_APPROVE=True`; production sets it to false and listings then get stuck. Listing reports have no visibility check. | None. | See Module 2. | build new |
| Ad approval | Works, with no state guard. | None. | Reason codes; audit trail. | keep + build new |
| Report intake | The generic endpoint accepts every target type with no visibility check. An event without a reporter dead-letters. | None. | Content reports go through the owning service, with visibility checks; the generic endpoint is limited to user and page, and that change lands before evidence snapshots exist. | build new |
| Queue and triage | Ordered by report count; severity is never set; `assign()` reopens resolved cases. | None. | Severity, filters, keyset paging on a packed triage key. | build new |
| Evidence | None. | None. | Snapshot fetched from the owning service; media held while a case is open. | build new |
| Enforcement and reversal | Reversal works only for posts and for removed listings. Chat removal cannot be undone, because it uses the same `deleted_at` as an author's own delete. | None. | A reversal map per action; a separate `moderation_removed_at` in chat. | build new |
| Appeals | No owner check and no state check. The resolver is recorded only in the audit log. An overturn always emits `approve`, whatever the original action. | None. | Owner-only appeals within a time window; four-eyes resolution; the inverse of the original action on overturn. | build new |
| Blocked content | None. `PENDING` is never set, and a `PENDING` post would still be visible. | Arabic normaliser without NFKC, zero-width stripping or Persian letter folding. | A shared matcher in `libs/tara_common`, evaluated when content is written, so a hold applies before publication. | take algorithm (hardened) |
| Content policies | `ContentPolicy` model exists, unused. | None. | Versioned policies in ar and en. | build new |
| Audit log | Minimal and write-only; written after the remote call has already happened. | Index set and filters (`backend/core/models.py` `AuditLog`, `backend/access/views.py`). | Unified, fed by events, cursor-paginated API, CSV export. | take design |
| Security panel | `SecurityEvent` cannot be read in production. | `MonitorView`: failed logins and most-targeted accounts, but it groups by a description string that contains the email. | Aggregation by `account_id` inside identity. | take design (the concept) |
| Statistics | None; the analyst role is checked nowhere. | Versioned cache (`backend/core/cache.py`); a missing version key resets to 1, so stale entries can come back. | `MetricDaily` upserted inside the consumer transaction. | build new |
| RBAC and capabilities | Coarse role claim only. | Precedence order (`backend/access/services.py`) and a matrix editor (`frontend/src/pages/app/modules/AdminPermissions.vue`). | Capabilities computed by identity into a `caps` claim. | take algorithm (precedence) + take design (matrix UI) |
| Role management | Present. The identity internal API trusts `actor_id` from the request body, and the same `INTERNAL_JWT_SECRET` is in every container. | n/a | A separate admin-to-identity secret, built in roadmap 1.0d. Identity picks the verification key by caller and rejects the shared secret. An issuer check alone would not be a control, because every holder of the shared secret can set any `iss`. | build new |
| System settings | `SystemConfig` model exists, unused. | `backend/cms/chrome.py` catalogue (no number kind; unknown keys dropped). | Schema registry, validated PATCH, change event. | take design |
| Feature flags | No runtime effect anywhere. A partial PATCH resets the other fields. | n/a | True partial update; evaluate endpoint; a server-side client later. | build new |
| Service health | Polls 11 services one after another; `ads`, `realtime` and `bff` are missing; one snapshot row per request. | `_ping` timing wrapper (also sequential). | Beat job polling every 60 s in parallel; outbox and DLQ backlog shown. | build new |
| Console polling UX | n/a | `frontend/src/pages/app/modules/AdminMonitor.vue`: polls every 15 s, pauses when the tab is hidden, mounts tabs lazily and keeps them alive. | Same behaviour in TypeScript. | take design |

## What we take from QTech, what we leave, and why

QTech is a single-company portal: a Django 4.2 monolith with 11 apps and a Vue 3 frontend in plain JavaScript. Its internal social system is even labelled "Tara" in the navigation (`frontend/src/config/nav.js`). It is an early prototype of some Tara ideas, not a codebase to merge.

Three facts drive every decision above:

1. **Tara's architecture is stricter.** In Tara, services own their data and cross-service data flows through the outbox or internal HTTP. QTech joins across apps freely, writes other apps' tables from `post_save` signals (`backend/accounts/signals.py`), and sends realtime pushes and emails inside the request. QTech code therefore never moves over as-is; at most its logic does.
2. **QTech is mostly untested.** The backend has 70 tests in three files (`backend/cms/tests_pages.py`, `backend/hr/tests.py`, `backend/tasks/tests.py`). There are none for social, chat, realtime, notifications, accounts, access, billing or theming. There are no frontend tests and no CI. Every ported piece gets Tara tests when it arrives.
3. **QTech's UI cannot be copied.** It is plain JavaScript, with hard-coded Arabic in 86 files and 27 hard-coded `'ar-EG'` formats. Tara is TypeScript with vue-i18n and an ar/en parity test. UI is always rewritten; only layouts and interaction rules carry over.

### Algorithms we take (logic ported, with fixes and tests)

| Algorithm | QTech source | Used in Tara for | Fix before porting |
|---|---|---|---|
| Multi-tab presence with heartbeat TTL and `last_seen` | `backend/core/realtime.py` | Messenger presence (`services/realtime`) | One self-expiring ZSET per account instead of a counter hash with no TTL; presence sent only to authorised peers; UUIDs, not `int()` ids. |
| Visibility clock and beacon clamps | `frontend/src/composables/useVisitorTracking.js`, `backend/core/tracking.py` | Video watch time, reels telemetry, ad viewability | The clock counts only while the element is visible (and, for video, playing). Ingestion goes to Redis rather than one Postgres write per beacon. Use keepalive fetch where auth is needed. |
| Arabic text normalisation (`_norm`) | `backend/core/chatbot.py` | Search, trending tags, blocked terms, message search, skill catalogue | Add NFKC, zero-width and bidi stripping, Persian ک/ی folding and digit folding. Do not drop stop-words when matching phrases. The skill variant must keep symbols. |
| Comment flattening (`parent` = root, `reply_to` = target) | `backend/social/views.py` `CommentViewSet.perform_create` | Post comments | Keep Tara's rule that the post is derived from the parent (QTech lets clients write `parent`). Paginate replies. |
| Image safety guards | `backend/core/images.py` | Video posters, avatars and covers | Pixel cap; the no-upscale test as `<`, not `<=`; write to S3 instead of the filesystem. |
| HEIC to JPEG | `frontend/src/utils/heic.js` | Post composer, avatar, listings, thumbnails | Keep the chunk out of the service-worker precache. Server-side MIME and magic-byte checks remain the real control. |
| Push subscription lifecycle | `frontend/src/mobile/push.js` | Notifications | Add a local unsubscribe on every logout path; re-bind the subscription on login. |
| Capability precedence | `backend/access/services.py` | Admin RBAC | Compute once into a token claim (QTech runs 2 queries per check); validate keys against a registry; audit every change. |
| Geo lookup and atomic DB refresh | `backend/core/geo.py`, `backend/core/management/commands/update_geoip.py` | Ads country targeting | Read the Cloudflare header before the private-IP check; Country Lite only (CC-BY attribution); trust headers only behind a known proxy chain. |
| View-count cooldown | `backend/core/visitors.py` | Marketplace listing views | Buffer in Redis and flush in a job instead of one DB write per hit. |
| Small helpers | `backend/core/export.py` (CSV BOM), `frontend/src/utils/sound.js` (ping), `backend/core/attribution.py` (bot UA markers), `frontend/src/mobile/composables/useSwipeBack.js` (RTL swipe thresholds) | Ads and admin exports, notifications, ads fraud, reels gestures | CSV formula-injection guard; a bot UA match is a weak signal, because all Tara APIs require auth anyway. |

### Designs we take (shape reused, code rewritten)

| Design | QTech source | Tara module |
|---|---|---|
| LiveKit SFU deployment and runbook | `infra/livekit/` | Messenger calls. Add webhooks, TURN, room limits and an exact image tag. |
| LiveKit client engine and call overlay | `frontend/src/composables/useLiveKitCall.js`, `frontend/src/components/chat/CallOverlay.vue` | Messenger. Room names come from the server, identities are UUIDs, and call frames are filtered by call id. |
| Photo grid and URL-backed theater | `frontend/src/components/social/PostFeed.vue` | Social, Profiles, Marketplace galleries |
| Crawler link previews | `frontend/nginx.conf`, `backend/cms/social.py` | Social, Marketplace, Video, Reels, Profiles. Escape JSON-LD, build `og:url` from the public route, serve og:image on a public path, keep throttles on. |
| Applicant tracking model (job, application stages, interview panel, feedback) | `backend/hr/models.py` | Professional |
| Recruiter pipeline layout | `frontend/src/pages/app/modules/HrRecruitment.vue`, `TasksBoard.vue` | Professional |
| Applicant field stripping and write-locking | `backend/hr/serializers.py` | Professional |
| Three-state price and effective-price ordering | `backend/cms/models.py` `Product`, `backend/cms/views.py` `ProductViewSet` | Marketplace |
| Filter chips and sort sheet | `frontend/src/components/ui/FilterChip.vue`, `SortSheet.vue` | Marketplace |
| Read pointers, clear-for-me, per-member archive | `backend/chat/models.py`, `backend/chat/serializers.py` | Messenger |
| Edit / delete / forward semantics | `backend/chat/views.py` | Messenger. Add an edit window and attachment copying. |
| Event and RSVP shape | `backend/social/models.py` | Social |
| Audit index set and filters | `backend/core/models.py`, `backend/access/views.py` | Admin |
| Permission matrix editor | `frontend/src/pages/app/modules/AdminPermissions.vue` | Admin |
| Settings catalogue that drives a generated form | `backend/cms/chrome.py` | Admin system settings, marketplace category attributes |
| Soft-delete manager pair | `backend/accounts/managers.py` | Profiles |
| Inline notification actions, per-type deep links, live list | `frontend/src/components/social/NotificationBell.vue`, `frontend/src/composables/useNotifications.js` | Notifications |
| Pull-to-refresh, URL-backed sheets, poster-as-LCP contract | `frontend/src/mobile/components/PullToRefresh.vue`, `PostFeed.vue`, `frontend/src/components/ui/SmartImage.vue` | Reels |
| Admin monitor polling | `frontend/src/pages/app/modules/AdminMonitor.vue` | Admin |

### What we leave, and why

- **Monolith coupling.** Cross-app foreign keys and imports (hr ↔ tasks ↔ social), signals that create rows in other apps, and pushes or emails sent inside the HTTP request with no outbox. Tara already has the outbox and idempotent consumers, which is the right replacement.
- **QTech's auth model.** HS256 SimpleJWT signed with `SECRET_KEY`; access and refresh tokens in `localStorage`; the WebSocket token in the query string; no session revocation on password change or suspension. Tara's identity service (RS256 with JWKS, rotating refresh tokens with reuse detection, httpOnly refresh cookie) is already stronger.
- **Local file storage.** FileFields on a shared volume served by nginx. Signed attachment URLs can be bypassed through `/media/chat/`. Tara keeps MinIO with presigned URLs.
- **Company-specific domains.** HR, payroll, attendance, tasks, the landing-page CMS, client billing and the website chatbot have no counterpart in a social ecosystem.
- **Global presence broadcast and P2P mesh calls.** Presence sent to every connected user is a privacy and scaling problem. The mesh engine ships static TURN credentials in the public bundle.
- **Request-time analytics over raw tables.** Tara aggregates into daily tables in the owning service instead.
- **Unsafe patterns found in QTech's code.** These are not repeated in Tara. They are listed so Tara tests can guard against them:
  - Anonymous read of user records, possibly without login, through `IsSelfOrCanManage` (`backend/accounts/views.py`, `backend/accounts/permissions.py`). Found by reading the code; not executed.
  - HR can create super-admins through a writable `role` field (`backend/accounts/serializers.py`).
  - LiveKit room name taken from the client (`backend/chat/views.py`), and `call.*` frames relayed to any user id (`backend/core/consumers.py`).
  - Profile timeline IDOR (`backend/social/views.py` `SocialProfileViewSet.posts`).
  - Contact messages and newsletter subscribers readable anonymously (`backend/cms/views.py`).
  - Published pages return their unpublished `draft_blocks` to anonymous readers (`backend/cms/serializers.py`).
  - An anonymous job application overwrites an existing candidate matched by email (`backend/hr/careers.py`).
  - Task approval gates bypassed through PATCH (`backend/tasks/views.py`, `backend/tasks/serializers.py`).
  - Chat attachments served inline with the client-supplied Content-Type (`backend/chat/views.py`).
  - Offline chat emails list every recipient in one To: header (`backend/chat/tasks.py`).
  - Default VAPID keys committed in `backend/qtech_config/settings.py`, and hard-coded seed passwords in `backend/core/management/commands/seed_demo.py`. The values are not reproduced here. They should be rotated in QTech and never reused in Tara.

### What Tara already does better (nothing to import)

- Identity: RS256 with JWKS, refresh rotation with reuse detection, and DB-backed hashed verification and reset tokens.
- Feed: fan-out on write, with stale snapshots fetched again through `/posts/batch/`.
- Graph: friendships, follows, blocks, and block read models in each consuming service.
- Notifications: per-kind preferences, timezone-aware quiet hours, and Web Push with an SSRF endpoint allowlist.
- Media: presigned uploads with magic-byte checks for images and PDFs.
- Engineering: CI, 15 green service suites, vitest and Playwright.

## Corrections from the verify pass

The verify pass changed these audit claims. The tables above use the corrected versions.

- **Social – comments.** Tara already shows the "replied to X" label. The real bug is replies orphaned across pages.
- **Social – reactions.** `suppressClick` already exists in `PostActions.vue`.
- **Social – video.** Video is not just "missing": the backend path exists and is unsafe today.
- **Social – reporting.** Moderation already accepts comment, user and page reports, and already dedupes per reporter; no migration is needed.
- **Social – privacy.** `SocialMutualView` also leaks friend lists.
- **Social – theater.** The photo theater lives in `PostFeed.vue`, not `PhotoViewer.vue`.
- **Marketplace – money formatting.** The QTech money formatter rounds fractional 3-decimal amounts to 2 decimals (checked in Node 24).
- **Marketplace – facets.** The QTech facets endpoint has one dimension and includes its own filter.
- **Marketplace – pending review.** Production already runs with `MARKETPLACE_AUTO_APPROVE=false`, so new listings get stuck today.
- **Marketplace – contact.** Neither the UI nor `ContactView` sends a buyer message.
- **Video – posters.** QTech's no-upscale test skips the rung equal to the source width. Tara's thumbnail code already applies EXIF transpose and never upscales.
- **Messenger – presence.** QTech presence recovers after a crash through the ZSET TTL; it is the counter hash that drifts.
- **Messenger – groups.** `create_group` never enforces `MAX_GROUP_MEMBERS`.
- **Messenger – read receipts.** Read pointers are exposed to every member over REST.
- **Ads – double billing.** The UI's default values bill every ad set both per click and per impression.
- **Ads – serve tokens.** The `pl` claim is signed but never checked.
- **Ads – rounding.** Per-impression CPM rounding at 4 decimals loses or adds money.
- **Professional – applications.** QTech's application stage is writable through PATCH; the "dedicated action only" claim was wrong.
- **Professional – list endpoints.** The Tara `FieldError` on work and links lists is certain, not "likely".
- **Professional – CV size.** `MediaAsset.bytes` is client-declared, so a size cap based on it can be bypassed.
- **Profiles – display name.** The 120/80 length mismatch sends `account.registered` to the DLQ, so some users never get a profile.
- **Profiles – default handle.** Default handles come from the email local part.
- **Profiles – friends tab.** The SPA renders the friend list of restricted profiles.
- **Notifications – marketplace.** The seller self-notification bug comes from the notification handler not passing `actor_id`.
- **Notifications – push clicks.** The service worker drops query strings and hashes on notification click.
- **Admin – suspension.** There is no reachable suspension path in production, because nginx does not route `/admin`.
- **Admin – feature flags.** Flags have no runtime effect anywhere.
- **Admin – appeals.** An overturned appeal always emits `approve`, whatever the original action.
- **Admin – chat removal.** Chat removal cannot be reversed.

## Not verified

These points were judged plausible but not confirmed. Check each one before relying on it.

- Whether Dokploy's Traefik v3 `readTimeout` cuts off slow uploads of 150–200 MB.
- Whether `pg_trgm` extracts usable trigrams from Arabic text on postgres:16-alpine.
- Whether the lazy `heic2any` chunk loads under Tara's production CSP.
- TURN behaviour when the LiveKit domain sits behind the Cloudflare proxy (UDP does not pass the proxy).
- Whether QTech's nginx adds Content-Disposition or a sandbox CSP for uploaded HTML/SVG files.
- QTech's anonymous user-read flaw was found by reading the code only; it was not executed.
