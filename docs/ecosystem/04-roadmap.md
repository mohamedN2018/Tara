# Tara ecosystem implementation roadmap

Ecosystem review, part 4 · Branch `feat/web-social-platform` · 2026-11-03

**Audience:** Tara engineers and the product owner (Mohammed).

**What this is:** the ordered build plan for the ten product modules of the Tara ecosystem. For each step it gives the goal, the owning services, the milestones with effort in days, dependencies, acceptance tests, risks and what is deferred (with the reason). It ends with the total effort, the critical path, a concrete plan for the first two weeks, launch gates and the decisions the product owner needs to make.

**Status:** plan only. Nothing in this document has been built.

The current state of the code is described in the companion document [02-tara-audit.md](02-tara-audit.md). This roadmap does not repeat that inventory; it says what to build next and in what order.

---

## Contents

1. [How to read this roadmap](#1-how-to-read-this-roadmap)
2. [Summary](#2-summary)
3. [Ground rules for every step](#3-ground-rules-for-every-step)
4. [Decisions that avoid building things twice](#4-decisions-that-avoid-building-things-twice)
5. [Platform gate and pull-forward items](#5-platform-gate-and-pull-forward-items) (milestone 1.0 and the launch hardening track L)
6. [Step 1 — Shared social core](#step-1--shared-social-core)
7. [Step 2 — Profiles + notifications](#step-2--profiles--notifications)
8. [Step 3 — Messenger](#step-3--messenger)
9. [Step 4 — Marketplace](#step-4--marketplace)
10. [Step 5 — Video + reels](#step-5--video--reels)
11. [Step 6 — Ads manager](#step-6--ads-manager)
12. [Step 7 — Professional](#step-7--professional)
13. [Step 8 — Admin dashboard](#step-8--admin-dashboard)
14. [Step 9 — Design system pass](#step-9--design-system-pass)
15. [Step 10 — Integration tests](#step-10--integration-tests)
16. [Total effort and staffing](#16-total-effort-and-staffing)
17. [Critical path](#17-critical-path)
18. [The first two weeks](#18-the-first-two-weeks)
19. [Launch gates (recommendation)](#19-launch-gates-recommendation)
20. [Deferred work, consolidated](#20-deferred-work-consolidated)
21. [Decisions needed from the product owner](#21-decisions-needed-from-the-product-owner)
22. [Sources and verification](#22-sources-and-verification)

---

## 0. Implementation status

| Milestone | Status | Notes |
|---|---|---|
| 1.0a CI lint and vitest | Done | `.github/workflows/ci.yml` |
| 1.0b Ads serving switch | Done | `ADS_SERVING_ENABLED`; off by default when `TARA_ENV=production`; deploy check errors if on in production |
| 1.0c DLQ broker migration | **Not started** | Needs the policy-based migration and a broker rehearsal described in 1.0c |
| 1.0d Caller-specific secret for identity's role API | Done | `ADMIN_IDENTITY_SECRET`, `iss=admin`, `aud=identity.roles`; the shared secret is rejected there |
| 1.0e Ads-only serve-token secret | Done | `ADS_SERVE_TOKEN_SECRET`; old tokens are rejected immediately (no 30-minute grace window) |
| 1.1 Social-core correctness | Done | Feed, search, graph and post parts; backfills `relabel_feed_reasons` and `reconcile_hashtags` |
| 1.2 Moderation hardening | Done | Owner-only appeals, 409s, row locks, first-report race, report throttle, `owner_id` on `post.reported` and `listing.reported`; moderator appeal queue `GET /moderation/appeals/` |
| 1.3 Comments v2 | Done | Flattened threads (`reply_to`), paged replies, edit/delete, comment reactions, per-post comment policy, comment reports (moderation consumes `comment.reported`) |
| 1.4 Reaction and share lists | Done | `PostReactionCount`, who-reacted by type, who-shared, `post.unreacted` |
| 1.5 Media privacy and upload safety | **Done** | Safety part: see the design note below. UX part: media grid, `?view=` viewer. HEIC is converted to JPEG on the server (pillow-heif in media), so the strict CSP stays; files, audio and voice download as attachments under their own name |
| 1.13–1.14 Events (gatherings) | Done | Post `gatherings` app: `/api/v1/events/` (tabs upcoming, hosting, going, invited, past; keyset, filtered in SQL before paging; title search), detail, edit, cancel, delete, RSVP (capacity under the event's row lock, 409 `event_full`, no waitlist; the host does not RSVP), attendees by state (not going and invited for the host only), friends-only invites through graph, report (enum reasons, deduped, `ReportThrottle`). One visibility rule (public, friends, invite-only; blocks both ways; hidden is 404). Cover bound and restricted in media through post's visibility endpoint. Events `gathering.created/updated/cancelled/deleted/rsvp/invited/reminder/reported` with JSON Schemas; reminders about 24 h and 1 h before, once each (`gatherings.tick` beat). Moderation `gathering` target; notification kinds `gathering.invite/reminder/update/cancel/rsvp`. Web: `/events`, `/events/new`, `/events/:id` (RSVP, people, invite, share as a post, report, host edit and cancel). Not built: waitlist, page or group hosts, feed cards, search-service indexing (1.15) |
| 2.14–2.17 (most), 2.18 (part) Notifications v2 | Done | Kind registry and deep links, aggregation, inline actions, live list with cross-tab and cross-device sync, per-kind in-app/push prefs, sound, push lifecycle. Not built: quiet-hour deferral, device list, digest (2.19) |
| Step 3 messenger (QTech port) | Partly done | Presence (multi-tab, last seen, peers only), seq read pointers and unread counts, archive, clear for me, edit/delete/forward, search, shared media, file/video attachments. Run `backfill_message_seq` once after deploy |
| 3.7 1:1 calls, 3.8 group calls (basic) | Partly done | `livekit` container (v1.13.10, `COMPOSE_PROFILES=calls` on Dokploy), edge `/rtc`; chat `calls` app: server-generated room per call, `livekit-api` tokens (≤ 10 min, one room, identity = account), one live call per conversation under the conversation lock, 45 s ring sweeper, signed webhook read from the raw body (idempotent), reconcile job, kick on member removal or block; `call.*` events, call-log system messages; realtime `call.*` frames; notification push-only ring path (tag `call:<id>`, cleared on answer, decline or end) and an in-app `call.missed` kind; SPA overlay (incoming, outgoing, in-call, 9-tile grid with spotlight, screen share, rejoin banner). Calls are off while `LIVEKIT_API_KEY`/`SECRET` are empty. Not built: raise hand, TURN tested from a mobile network, Playwright run in both languages with axe |
| Step 4 marketplace (4.3, 4.4, parts of 4.6–4.8) | Partly done | Three price types, filters/sort/facets, Arabic-aware search, view counter, favorites, compare, inquiries, seller page and reviews (moderation consumes `marketplace.review.reported`). Not built: lat/lng radius (4.5) |
| Account security (QTech port) | Done | Google sign-in and linking, per-email login throttle, change password and email, Telegram phone verification |
| Hardening pass after wave B | Done | Six-area review with a failing-first test per fix. Highlights: account takeover through a pending email change after a password reset; identity rejects tokens of ended sessions at once; oversize `X-Request-Id` 500s everywhere; group history before joining; removed or blocked members keeping live subscriptions; presence after a block; stale events reviving deleted posts in feeds; link-preview slow-drip; ad budget overspend under concurrency; self-approval of ads; media re-bound from a live post; handles derived from emails. Open items are listed below |
| 8.1 Event plumbing, capability registry, unified audit | Done | `tara_common.capabilities` (namespaced keys, default role map, implies) and `HasCapability`; admin outbox, `admin-consumer` and `admin-worker`; `AuditEntry` from `account.role.granted/revoked`, `capability.matrix.changed`, `moderation.actioned`, `appeal.resolved` (new), `ad.review.decided`, plus admin's own flag changes and exports; `GET /admin/audit/` (keyset) and `/admin/audit/export.csv` (streamed, row cap, formula guard, BOM, itself audited). nginx sets `X-Request-Id` and drops `X-Geo-Region`; dev Traefik strips both |
| 8.11 Platform statistics (monitoring part) | Done | Health polled in parallel by beat every 30 s with the existing pruning; the API reads snapshots. Counts polled every 5 min from each owner's `/internal/v1/stats/` (exact, no backfill, no new events) instead of event counters; `GET /admin/monitor/`. Not built: DLQ and outbox visibility |
| 8.12 Capability matrix | Done | `caps` claim (sorted) in access tokens, the raw email removed; per-role grant/revoke overrides in identity behind `ADMIN_IDENTITY_SECRET`; the locked `admin` role keeps every key; matrix editor with diff preview; moderation, ads review and admin endpoints moved to capabilities. Tokens without `caps` derive them from roles |

**Known open items after the hardening pass** (each needs a product decision, a new event, or a cross-service change):
- Other services accept an access token until it expires (up to 15 minutes) after sign-out; only identity checks the session. Closing it needs a shared deny-list.
- Marketplace review eligibility is a one-way inquiry; the two-way rule (4.8) needs chat reply events (4.7). Age and per-seller brakes are in place.
- `message.reported` has no producer: reporting a private message needs an evidence-snapshot decision.
- DLQ topology is shared by all services (1.0c broker migration).
- Registration answers 409 for a taken email (enumeration, throttled).
- Unread counts include messages deleted for everyone; presigned URLs live 15 minutes after access is lost; a sent push cannot be recalled.

**Design as built for 1.5 (differs from the row below):** post media is restricted
when the post's audience is not public. Post binds the media to the post through
`POST /internal/v1/media/bind/` before it writes; restriction only ever narrows.
For a restricted asset, media asks post `GET /internal/v1/posts/<id>/visibility/`
(the same resolver as the public API, 2 s timeout, circuit breaker, fails closed),
so the SPA keeps using `/media/<id>/` unchanged. Strangers, blocked users and
ex-friends get 404. EXIF/GPS is stripped from every image before READY
(`sanitize_existing_images` cleans older ones). Uploads are single-use through a
`staging/` key, with real size, ETag and signature checks. Video posts return
`400 video_not_supported_yet` until step 5. Still open: media of deleted or
removed **public** posts stays fetchable by id until media consumes `post.deleted`.
Media's internal endpoints still accept the shared internal secret (a
caller-specific key, as in 1.0d, is a follow-up). A URL already handed out stays
valid for up to 15 minutes after an unfriend or block.

## 1. How to read this roadmap

- **The order of the ten steps is fixed by the product owner:** shared social core → profiles + notifications → messenger → marketplace → video + reels → ads manager → professional → admin dashboard → design system pass → integration tests. This is the priority order. For a single engineer it is also the build order. With more engineers, the next free engineer takes the earliest step whose dependencies are met (see [section 17](#17-critical-path)).
- **Effort is in engineer-days** for one senior engineer who already knows Tara's conventions (outbox events, `tara_common` envelopes and cursor pagination, `scripts/test-service.sh`). A day includes the code, its tests and its docs (the documentation each milestone owes is listed in [06-documentation-plan.md](06-documentation-plan.md)). It does not include code-review wait time, production incidents or holidays. All numbers are design-time estimates, not measurements. They are optimistic for Tara's real situation: `docs/architecture/project-review-and-plan.md` §6 describes one developer running 43 containers on one server. That is why the contingency is 35–50% ([section 16](#16-total-effort-and-staffing)), not the usual 20%.
- **Milestone IDs** are `<step>.<n>` (for example `1.7`). The **Source** column names the module design the milestone came from (for example "Social M5"), so engineers can trace the full endpoint and model lists in those designs. When two designs described the same work, it appears once here (see [section 4](#4-decisions-that-avoid-building-things-twice)).
- **Verification corrections are applied.** Every module design had an independent verify pass that re-read the code. Where it refuted or corrected a design claim, this roadmap uses the corrected version, and each step lists the corrections that change scope.
- **QTech is a read-only reference.** "QTech reuse" lines name patterns worth porting from the QTech codebase. Nothing is copied wholesale, and several QTech defects are named explicitly so they are not ported.
- **Acceptance tests** listed per step are the key ones that prove the step. Each milestone also carries the fuller test list from its module design.

---

## 2. Summary

| Step | Scope | Main services touched | Base effort (days) |
|---|---|---|---|
| 1 | Platform enablers (CI with Playwright, DLQ broker migration, caller-specific internal secrets, deploy safety, Redis limit), then the shared social core: correctness fixes, comments v2, private media with EXIF stripping, relationship privacy, smart feed ranking, trending, stories, groups with suggestions, events, search v2, report endpoints, crawler previews | post, feed, graph, search, profile, moderation, media, identity, ads, `libs/*` | 72 |
| 2 | Profiles (handles, links, tabs, lock, mention privacy, business pages, posting as a Page, activity log, age gate) + notifications (deep links, aggregation, live list, preferences, new sources, email digest) | profile, notification, post, feed, graph, identity, realtime | 54.5 |
| 3 | Messenger: presence, private attachments with file and video composer, message lifecycle, inbox state, search, message requests, 1:1 and group calls on LiveKit, file scanning | chat, realtime, media, notification, new `livekit` and `media-scanner` containers | 39.5 |
| 4 | Marketplace: hardening, photos, prices and categories, search and facets, location, business sellers, inquiries, reviews, comparisons, orders foundation with order notifications | marketplace, chat, moderation, search, notification | 37 |
| 5 | Video + reels: one media video pipeline, HLS, video and reel domains, unified watch telemetry, players, profile Videos and Reels tabs, listing video, library, discovery, reels ranking, creator studio, sounds, captions | media, post, feed, search, notification, marketplace, new `media-transcoder` container | 90 |
| 6 | Ads manager: correctness, ad accounts, prepaid funding with verification, campaign builder, sponsored posts and listings, targeting, insights, fraud, conversions, video and reel ads | ads, post, marketplace, profile, identity, notification, moderation | 52 |
| 7 | Professional: skills, certifications, CVs, company pages, jobs, applications, recruiter dashboard, interviews, endorsements, job alerts | profile (new `careers` app), media, graph, search, notification | 31.5 |
| 8 | Admin dashboard: unified audit, case evidence, suspensions and their propagation, user and page management, appeals, blocked content, policies, statistics, capabilities, system settings | admin, moderation, identity, plus consumers in every service | 44.5 |
| 9 | Design system pass: tokens, RTL and i18n, accessibility, shared primitives, performance | frontend/web | 13.5 |
| 10 | Integration tests: smoke and contracts in CI, event contracts, cross-module journeys, privacy matrix, resilience, load, deploy rehearsal | all | 19 |
| L | Launch hardening ([section 5.3](#53-launch-hardening-track-l)): production observability, dedicated beat, Postgres and Redis sizing, staff 2FA, account erasure, CSAM process | infra, identity, all services | 29 |
| Docs | Documentation work not already inside a milestone ([06-documentation-plan.md](06-documentation-plan.md)): ADR backfill, staff guides | docs | 5 |
| | **Total (base)** | | **487.5** |
| | **With 35% contingency** | | **≈ 658** |
| | **With 50% contingency** | | **≈ 731** |

Calendar, assuming 4 productive engineering days per week (the fifth goes to reviews, deploys and bug fixing):

| Team | Bound by | Base | +35% | +50% |
|---|---|---|---|---|
| 1 engineer | total effort | ≈ 122 weeks | ≈ 165 weeks (about 3.2 years) | ≈ 183 weeks (about 3.5 years) |
| 2 engineers | total effort | ≈ 61 weeks | ≈ 82 weeks (about 19 months) | ≈ 91 weeks (about 21 months) |
| 3 engineers | total effort, close to the critical path | ≈ 41 weeks | ≈ 55 weeks (about 13 months) | ≈ 61 weeks (about 14 months) |

The critical path (the longest chain of milestones that must happen one after another) is about 134.5 days. Details are in [section 17](#17-critical-path).

---

## 3. Ground rules for every step

### 3.1 Architecture rules (unchanged)

- **No new services.** `docs/architecture/project-review-and-plan.md` §5.2 says "لا خدمات جديدة". New domains go into existing services as separate Django apps (for example `stories`, `gatherings` and `reels` in post; `groups` and `careers` in profile) so they can be extracted later. Third-party infrastructure (LiveKit, the transcoder worker) is added as containers, not services.
- **Services own their data.** Other accounts, media and listings are referenced by bare UUIDs. No cross-database foreign keys and no shared tables.
- **Cross-service writes go through the outbox**, in the same transaction as the state change (`tara_events.outbox.record_event`). Consumers are idempotent `@on_event` handlers; renaming a handler resets its dedupe key.
- **Synchronous calls are internal reads only**, under `/internal/v1/`, with short-lived HS256 tokens, a circuit breaker and a timeout. Visibility checks fail closed.
- **API contract:** `{"data": ...}` envelopes, cursor pagination (`?cursor=`, `?limit=` up to 100, never raw offsets), `{"error": {...}}` errors.
- **Edge routing:** any new top-level `/api/v1/<prefix>` is added to both `frontend/web/nginx.conf` and the Traefik labels in `infra/compose/docker-compose.yml`. The Kubernetes manifests stay frozen (`docs/architecture/project-review-and-plan.md`).

### 3.2 Definition of done for a milestone

1. Committed migrations, and `makemigrations --check` passes in `scripts/test-service.sh`.
2. pytest for every new path in the owning service, including the negative and privacy cases.
3. vitest for new frontend logic, and ar/en key parity (the existing parity test enforces it).
4. A Playwright flow for every new user-facing journey, run in Arabic (RTL) and English. The flow includes an axe check (no serious or critical violations), and new screens use brand tokens only (`tailwind.config.js`, `src/style.css`). Step 9 then consolidates; it does not retrofit.
5. New or changed events are documented in `docs/architecture/phase-0/04-event-contracts.md`, and each new event type gets a JSON Schema in `libs/tara_events/tara_events/schemas/`. Step 10 backfills schemas for the event types that already exist.
6. All 15 backend suites, vitest and Playwright stay green **in CI**. Playwright runs in CI from milestone 1.0f, so this rule is enforced from step 1. When a milestone deliberately changes behaviour that an existing e2e spec asserts, it rewrites that spec in the same PR. One milestone is one or a few small PRs.
7. The documentation listed for the milestone in [06-documentation-plan.md](06-documentation-plan.md) is updated: OpenAPI annotations, the event catalogue, runbooks and ADRs where they apply.
8. A deploy note for the step in `docs/deploy/DOKPLOY.md` lists new env var names (never values), new containers and their memory, the migration order, one-off commands and any event-emission flags. `scripts/gen-dokploy-env.sh` is updated in the same PR.

### 3.3 Patterns the verify passes found again and again

These came up in several modules. Every step must follow them; they are not repeated in each step.

| Pattern | Rule |
|---|---|
| One visibility function per entity | Lists and detail views use the same resolver. A hidden item returns 404, never 403. Every new list endpoint gets a viewer × audience test matrix. |
| Audience filtering after paging | Filter by audience in SQL before paging where possible (compute the viewer's relationship once), so pages are not short or empty with `has_more=true`. |
| Read models and event order | Retries reorder events. Read models store the source `occurred_at`, apply only newer events and keep tombstones for deletions. |
| Payloads on the bus | Shared-topic payloads carry ids and enums, not message bodies or other free text. Consumers fetch details through an internal endpoint when they need them. |
| Shared Redis | One Redis (`mem_limit 256m` in the Dokploy compose) serves every service, throttles and channel layers. Milestone 1.0h sets `maxmemory 200mb` with `noeviction`: a full Redis then refuses writes instead of being OOM-killed and losing everything. Never use an `allkeys-*` policy, because evicting a throttle bucket or an ads spend key reopens abuse. Heavy new uses (ranking sessions, telemetry streams) go to `redis-hot`, created in 1.7 with its own `maxmemory`. |
| Sizes and media trust | Trust the stored object's real size, never the declared size. From 1.5, images have their EXIF (including GPS) stripped before READY. Non-owners never get the original upload. |
| Media privacy | Media attached to content (posts, stories, group posts, chat, listings, CVs, receipts, video and reels) is private. The owning service mints short-lived URLs only after its own visibility check. Only account and page avatars and covers, public-group images and sounds stay public. |
| Internal secrets | `INTERNAL_JWT_SECRET` is shared by every service, so an `iss` claim proves nothing about the caller. Privileged endpoints verify a secret that only they and their named caller hold (identity from 1.0d). Tokens held by browsers (ads serve tokens) use a secret that only the issuing service holds (1.0e). |
| Crawler HTML | Escape `<`, `>` and `&` inside JSON-LD, html-escape meta values, and build `og:url` from the public route, never from the internal rewritten path. |
| Throttles | Setting `throttle_classes` on a view replaces the default read/write throttles; list them explicitly. Internal endpoints have no per-IP throttle. |
| Sync calls inside requests | Every service except identity runs with `ATOMIC_REQUESTS=True`. Do remote checks before opening the write transaction (the view is `non_atomic_requests` and opens its own atomic block), or use a local read model. When a remote **write** is unavoidable (a suspension, 8.4), call it first with an idempotency key, then commit the local change together with an outbox row, and run a reconcile job that repairs either side. |
| Migrations | Add indexes on large tables with `AddIndexConcurrently` in `atomic=False` migrations. Backfills commit per batch. `NOT NULL` changes go through `NOT VALID` then `VALIDATE`. Existing rows that a new rule would reject get an explicit data migration or command in the same milestone. |
| Deploy order | A Dokploy compose deploy recreates every changed container at the same moment, so deploy order cannot be enforced. A new event type therefore ships in two releases: the first adds the consumers (their queue bindings are declared at startup), and the second turns on emission behind a settings flag. The alternate exchange from 1.0g catches anything published with no binding. Workers and consumers wait for `manage.py migrate --check` before they start (1.0g), because only web containers run migrations. |
| Minors | No service stores an age today. Until the age gate (milestone 2.12) exists, no feature may personalise for, or publicly expose, an account as if it were an adult. |

---

## 4. Decisions that avoid building things twice

Several module designs planned the same work. Each item below is built once, in the step shown.

| # | Decision | Built in | Replaces |
|---|---|---|---|
| D1 | One media video pipeline (ffmpeg transcoder, posters, progressive MP4, HLS) serves video posts, long-form video, reels, listing video and video ads. Video posts therefore move from step 1 to step 5. Every video upload becomes a Video row; the post composer calls `/videos/` behind the scenes, so `Post.type=video` always has exactly one Video. Until 5.2 ships, creating a video post returns 400 (1.5), and listing video waits for 5.7. Chat video is the one exception: it is played as uploaded, but only after the 1.5 container-signature checks, privately and to conversation members only (3.2). | 5.2, 5.4 | Social M4, Video M1, Reels M1 |
| D2 | Relationship privacy (who sees friend/follower lists, who can send requests), counters, paginated lists and a batch relationship endpoint are owned by graph and built once. | 1.6 | Social M7, Profiles M3 |
| D3 | Posting as a Page, the profile internal page-member endpoint and page fan-out are built once, early, because marketplace business sellers, ads and professional all need them. | 2.7 | Professional M9 (and the post-as-page dependency in Social, Profiles, Ads) |
| D4 | Professional basics (work/education edit, headline, open-to-work, the list `FieldError` fix) move into the profiles step. Skills and certifications stay in step 7. | 2.1, 2.4 | Profiles M6, Professional M1 |
| D5 | Page follower counts come from graph. Profile does not keep its own `PageFollower` read model (the verify pass showed it would drift). | 1.6, 7.3 | Professional M4 read model |
| D6 | One Arabic text normaliser in `libs/tara_common`, with a separate variant for skill keys that keeps `+ # . / -` so C, C# and C++ stay distinct. | 1.8, 7.1 | normalisers in Social, Marketplace, Messenger, Professional, Admin |
| D7 | One media grid and URL-backed photo viewer, plus HEIC conversion, reused by profiles, marketplace, chat and video. | 1.5 | parts of Profiles M5, Marketplace M1, Messenger M1 |
| D8 | One watch-telemetry pipeline for long-form video and reels, owned by feed (ranking needs the signals hot), with token-authenticated beacons. Studio analytics read from it. | 5.6, 5.12 | separate telemetry in Video M5/M7 and Reels M6 |
| D9 | One crawler link-preview infrastructure (nginx user-agent map, internal rewrite, signed preview images). Later modules add a renderer for their own routes only. | 1.17 | OG work in Profiles M11, Marketplace M10, Video M8, Reels M10 |
| D10 | Notification aggregation per conversation, and clearing notifications when a chat is read, are built in the notifications milestone. Messenger does not rebuild them. | 2.16 | part of Messenger M3 |
| D11 | Moderation correctness hardening is pulled into step 1. Reporting is part of the social core, and the appeal-ownership bug is a listed open item. | 1.2 | Admin M0 |
| D12 | A self-declared age gate (date of birth or age band at signup, an `is_minor` flag in the token) is built once in identity. Reels, ads, marketplace and professional use it. Real age verification is deferred. | 2.12 | age work in Reels, Ads M10, Marketplace, Professional |
| D13 | Page moderation enforcement (a suspended page closes its jobs and leaves search) is built in step 7, where fake company pages first become a real risk. The admin console only adds the UI. | 7.10 | part of Admin M7 |

---

## 5. Platform gate and pull-forward items

### 5.1 Gate before step 1 (owner task, in parallel with week 1)

`docs/architecture/project-review-and-plan.md` lists these items as still open. They are platform work, not module work, but feature work should not go far without them:

| Item | Why now | When |
|---|---|---|
| Deploy the branch to a real Dokploy server with real SMTP, and test Web Push on a real browser | Every later milestone should be verified on a real deploy, not only locally | Week 1, owner |
| Decide MinIO vs Cloudflare R2 (the MinIO images could not be pulled; the doc lists this as a risk) | Storage choice affects step 3 attachments and step 5 video | Before step 3 |
| Restricted MinIO user instead of root | Required before the transcoder runs untrusted files (step 5) | Before step 5 |
| Moderation appeal ownership check | Built in milestone 1.2 | Week 3 |
| Refresh token in an httpOnly cookie only | Built in milestone 2.13 | Step 2 |

### 5.2 Items pulled into milestone 1.0

These unblock everything else and would be expensive to retrofit later. Two of them (1.0c and 1.0g) are broker changes on a live system, not plain code changes.

| ID | Item | Effort | Reason |
|---|---|---|---|
| 1.0a | CI runs `npm run lint` and `npm test` (vitest) | 0.5 | `.github/workflows/ci.yml` currently runs only `npm run build` for the frontend. The definition of done needs vitest in CI from day one. |
| 1.0b | Ads serving switch (`ADS_SERVING_ENABLED`, default off when `TARA_ENV=production`) plus a deploy check | 0.5 | Today campaigns go active on create with no payment check. Ads are rebuilt in step 6; until funding exists (6.3) no paid campaign may serve in production. |
| 1.0c | Dead-letter routing, planned as a **broker topology migration** | 2.5 | Every service binds its `<queue>.dlq` to the shared `<exchange>.dlx` with routing key `#` (`libs/tara_events/tara_events/worker.py`, line 51), so each DLQ receives every other service's failures. The obvious code fix does not work: main queues are declared with `x-dead-letter-exchange` and no `x-dead-letter-routing-key` (lines 68–74), and RabbitMQ refuses to redeclare an existing durable queue with different arguments (`PRECONDITION_FAILED`, 406), so every consumer would crash at startup after the deploy. Bindings are also additive, so the old `#` binding would stay. **Plan:** (1) set `dead-letter-routing-key` = the queue's own name with a per-queue RabbitMQ policy (`rabbitmq:3.13-management-alpine` supports it; a policy needs no redeclare, and the queue argument still supplies the exchange); (2) the worker binds `<queue>.dlq` with its queue name instead of `#`, and leaves the main queue's arguments unchanged; (3) a one-off topology script removes the old `#` bindings, drops the foreign copies already sitting in each DLQ (identified by the queue name in `x-death`) and has a rollback step (remove the policies, re-add `#`); (4) rehearse on a broker restored from a staging backup. **Fallback** if the policy route fails on the deployed version: stop the workers (the outbox holds new events), drain, delete and recreate the queues with the new arguments, then restart. **Acceptance test:** a handler failure in service A lands only in A's DLQ, and `consume_events --replay-dlq` in B replays nothing from A. |
| 1.0d | Caller-specific secrets on identity's internal API | 1 | `verify_internal_token` (`libs/tara_common/tara_common/auth.py`, lines 131–142) checks one HS256 secret, `INTERNAL_JWT_SECRET`, which `docker-compose.dokploy.yml` (line 32, the shared env block) gives to every service. Admin's client already sets `iss: admin` (`services/admin/adminsvc/identity_client.py`), but any holder of the shared secret can put any `iss` in a token, so **an issuer check is not a control**. Identity's `/internal/v1/` endpoints (role grants and account lookup) therefore accept only tokens signed with a secret that identity shares with one named caller: admin now, notification when 2.19 reads contacts, moderation when 8.4 suspends. Identity picks the key by caller and rejects tokens signed with the shared secret. A compromised service other than admin can no longer grant itself a role. |
| 1.0e | Ads serve tokens on their own secret | 0.5 | `services/ads/ads/serve_tokens.py` derives the serve-token key from `INTERNAL_JWT_SECRET` (an HMAC over a fixed label), so any service can forge billable impressions and clicks. Ads gets an ads-only secret (for example `ADS_SERVE_TOKEN_SECRET`). After the deploy, tokens signed with the old key are accepted for one token lifetime (30 minutes) and then rejected. |
| 1.0f | Playwright in CI | 2 | The definition of done says Playwright stays green, but nothing enforced that before step 10. Run the existing `frontend/web/e2e/` specs against the dev compose stack (`infra/compose/docker-compose.yml`) on every PR, in Arabic and English. Risk: the full stack (43 containers, 5.7 GB in `docs/architecture/project-review-and-plan.md`) may not fit a hosted runner, so use a reduced compose profile, a nightly full run, or a self-hosted runner. |
| 1.0g | Deploy safety for events and migrations | 1 | A Dokploy compose deploy restarts every changed container together, so "consumers before producers" cannot be enforced by ordering. The publisher uses `confirm_publish` without `mandatory` or an alternate exchange (`libs/tara_events/tara_events/publisher.py`), so an event published before its consumer's binding exists is confirmed, dropped, and marked published in the outbox. Only web containers run migrations (`RUN_MIGRATIONS=true`); workers and consumers start the new code against the old schema. **Fix:** (1) new event types ship in two releases, with emission behind a settings flag (section 3.3); (2) an alternate exchange on `tara.events`, set by policy as in 1.0c, routes unroutable events to `tara.events.unrouted`, with an alert and a replay command; (3) worker and consumer entrypoints wait until `manage.py migrate --check` passes. The steps go into the deploy runbook. |
| 1.0h | Redis memory limit | 0.5 | The shared Redis has `mem_limit 256m` and no `maxmemory` (05 §2.3). When full it is OOM-killed and drops every service's cache, throttles and WebSocket fan-out at once. Set `maxmemory 200mb` with `noeviction`, and add an 80% alert once L.1 exists. |
| | **Total** | **8.5** | |

### 5.3 Launch hardening track (L)

These items are required before real users arrive, but no module design scheduled them. They are platform work, so they do not change the order of the ten steps. The "Needed by" column says where each one must land.

| ID | Milestone | Days | Scope | Needed by |
|---|---|---|---|---|
| L.1 | Production observability | 5 | Bring the dev Prometheus, Grafana and OTel setup (`infra/observability/`, today wired only into `infra/compose/docker-compose.yml`) to Dokploy, plus Alertmanager and Loki for logs. Alerts for outbox lag, DLQ depth (per service, after 1.0c), `tara.events.unrouted`, consumer down, Redis memory, Postgres connections, disk and container restarts. Memory budget about 1 GB. | Invite-only beta |
| L.2 | Dedicated Celery beat | 2.5 | Each worker runs embedded beat (`-B -s /tmp/celerybeat-schedule`, `docker-compose.dokploy.yml` line 409 and the other workers), so the schedule is lost on every restart and workers cannot scale past one replica. Move beat into its own container with a persistent schedule on a volume (one per service, or one central scheduler that sends tasks by name; decide in this milestone). Heavy periodic jobs go to a `*.periodic` queue. | Before 1.8 (the first new periodic jobs) |
| L.3 | Postgres and Redis sizing | 1.5 | Set `max_connections` explicitly (about 150) and raise the Postgres `mem_limit` to match (05 §8.7); write the PgBouncer plan and its trigger. Plan Redis at 512m (container) before public launch. Size `redis-hot` after the reels load test. | Before step 3 (new consumers) |
| L.4 | Staff two-factor authentication | 4 | TOTP on top of identity's `two_factor_secret` scaffold, recovery codes, required for every account holding a staff role, enforced at token issue. | Before a second staff role is granted, and at the latest before step 8 |
| L.5 | Account deletion and erasure | 12 | An `account.deleted` / `account.deactivated` contract, a grace period in identity, an idempotent erasure consumer in every service with a database, media purge, data export, and an erasure audit row. | After step 8 (data models settled), before step 10 and public launch |
| L.6 | CSAM handling | 4 | A hash-matching vendor or service for public image and video uploads, quarantine through media's hold (5.3, 8.2), evidence preservation, a restricted-access escalation path, and a written process reviewed by legal. Vendor cost is not included. | Before public image and video uploads (public launch) |
| | **Total** | **29** | | |

L.5 used to be a deferred item marked "must ship before public launch", and staff 2FA was listed only as a step 8 dependency. Both now have estimates and count in the totals ([section 16](#16-total-effort-and-staffing)) and the critical path ([section 17](#17-critical-path)).

### 5.4 Operational note

`scripts/gen-dokploy-env.sh` sets `MARKETPLACE_AUTO_APPROVE=false`. Until milestone 4.1 lands, every listing published on a Dokploy deploy waits in `pending_review` forever, because moderation does not consume any review-request event. Either keep the marketplace closed on staging, or set the flag to true for testers only.

---

## Step 1 — Shared social core

**Goal.** Make the existing social core correct and safe, then add the missing social features: smart feed ranking, trending topics, stories, groups, events, people discovery, a better search and link previews when posts are shared.

**Owning services.** post (new Django apps `stories` and `gatherings` in `post_db`), feed, graph, search, profile (new `groups` app in `profile_db`), moderation, media (ownership checks, private media, EXIF stripping, a batch internal lookup and URL signing), identity and ads (1.0d, 1.0e), `libs/tara_common`, `libs/tara_events`. **New services:** none. **New container:** `redis-hot` (1.7).

### Milestones

| ID | Milestone | Days | Source | Scope notes |
|---|---|---|---|---|
| 1.0 | Platform enablers | 8.5 | [section 5.2](#52-items-pulled-into-milestone-10) | 1.0a CI lint and vitest; 1.0b ads serving switch; 1.0c DLQ routing as a broker migration; 1.0d caller-specific secrets on identity's internal API; 1.0e ads-only serve-token secret; 1.0f Playwright in CI; 1.0g deploy safety (two-release events, alternate exchange, migrate wait); 1.0h Redis `maxmemory` |
| 1.1 | Social-core correctness fixes | 3.5 | Social M0 | Feed: followers-audience posts also reach friends; the author is always kept when fan-out is capped; unfollow deletes only `reason=follow` items; unfriend also drops followers-audience items for non-followers; reason labelled friend or follow. **Data fix first:** every existing item is labelled `follow`, so a one-off `relabel_feed_reasons` command (paging graph's friendships through an internal endpoint) relabels items between friends as `friend` before the new unfollow rule is switched on; otherwise unfollowing a friend would delete their friend items. Search: hashtags indexed only from public posts, and stale hashtag documents removed. Post: `edit_post` refuses moderator-removed posts; `report_post` checks visibility and dedupes. Graph: friend, follower and mutual lists honour blocks; `block()` emits `friendship.removed`. |
| 1.2 | Moderation hardening | 3 | Admin M0 | `assign()` only on open cases; `take_action()` locks the row, validates the action per target type and returns 409 on resolved cases; first-report race handled; appeals owner-only, resolved cases only, one per case; generic report endpoint limited to user and page targets, with a report throttle; `owner_id` added to `post.reported` and `listing.reported` |
| 1.3 | Comments v2 | 3 | Social M1 | `reply_to_id` with flattening onto the thread root; edit and delete with `comment_count` decrement; paginated replies endpoint (fixes replies orphaned by pagination); comment reactions; per-post comment policy; comment report endpoint in post (404 when the reporter cannot see the comment) emitting `comment.reported` |
| 1.4 | Reaction and share lists | 1 | Social M2 | `PostReactionCount`, who-reacted (filter by type) and who-shared lists, `post.unreacted` event |
| 1.5 | Image media UX, ownership, privacy and upload safety | 6.5 | Social M3 + critic review | Media `POST /internal/v1/media/batch/` for lookup and URL signing; post checks owner, kind and ready status; server cap of 10 media ids per post. **Private media:** media attached to posts (and later stories and group posts) is private, and post mints short-lived URLs only after its own visibility check, for every audience, so an audience edit never has to flip media visibility; the SPA switches from `/media/<id>/` to the minted URLs, then a one-off `privatize_post_media` command makes existing post media private. **EXIF:** every image has EXIF and GPS removed before it becomes READY. **Upload safety:** `ftyp`, EBML and `OggS` signature checks for video and audio (today `matches_signature` returns true for every video and audio type, `services/media/media_app/validation.py`); uploads go to a staging key that `complete()` verifies and copies to the final key, so the presigned PUT (valid for 900 s and not revocable) cannot change an object after verification; real size and ETag stored; `Post.type=video` returns 400 until 5.2. UI: media grid (1/2/3/4+) and URL-backed photo viewer (`?view=`), with swipe and arrow keys mirrored in RTL; HEIC conversion as a lazy chunk excluded from the service-worker precache. See the notes below the table. |
| 1.6 | Relationship privacy, counters, batch relationships, suggestions | 5.5 | Social M7 + Profiles M3 | Graph-owned settings (list visibility, who can send friend requests); the discoverability flag is profile's `UserProfile.searchable` (05 §5, decision 9), carried in `profile.updated` and copied into graph `AccountRef` and feed; `AccountCounter`; profile summary endpoint; cursor-paginated friends, followers, following and mutual lists; `POST /social/relationships/` and an internal batch relationship endpoint; friends-of-friends suggestions that show only mutual counts and skip `searchable=false` accounts |
| 1.7 | Smart feed ranking v1 | 5.5 | Social M5 | Heuristic ranking (freshness, affinity, engagement) with For you / Latest modes; hide and snooze; signed opaque cursor with a latest-mode fallback; ranking sessions in `redis-hot`, a new Redis container created here with its own `maxmemory` and `noeviction`; non-public and explore items returned as ids only and hydrated through `/posts/batch/`; `searchable=false` authors never recommended |
| 1.8 | Trending, hashtag pages, Explore | 3.5 | Social M6 | `normalize_ar` in `libs/tara_common`; indexed `Hashtag.norm` column; trending counts distinct authors from public posts only; moderator blocklist; Explore page |
| 1.9 | Close friends and stories backend | 4 | Social M8 | `Post.audience` widened to 16 characters for `close_friends`; stories app with views, reactions and archive; story media private from upload, and post mints URLs only after the audience (close friends included), block and expiry checks; story report endpoint with the same check, emitting `story.reported` |
| 1.10 | Stories frontend | 3 | Social M9 | Tray, composer, full-screen viewer with RTL-aware gestures, archive |
| 1.11 | Groups backend | 7 | Social M10 | Groups app in profile; role hierarchy; join approval; group read models in post with a negative cache and synchronous checks for posting; group posts get a server-forced `group` audience, and their media URLs are minted only for members (anyone for public groups); group report endpoint in profile with a visibility check, emitting `group.reported`; **group suggestions** (Module 1): public and private groups that friends belong to, ranked by friend count, never secret groups, dismissible |
| 1.12 | Groups frontend | 4 | Social M11 | Group pages, admin queues, composer target, suggested groups |
| 1.13 | Events backend (`gatherings` app) | 4 | Social M12 | RSVP, capacity under a row lock, friend-only invites, reminders with recipients chunked per event; gathering report endpoint with a visibility check, emitting `gathering.reported`. Required by Module 1. |
| 1.14 | Events frontend | 2.5 | Social M13 | Event pages, RSVP, invites. Required by Module 1. |
| 1.15 | Global search v2 | 3 | Social M14 | pg_trgm and normalised columns; custom keyset paginator on (similarity, id); groups, events and hashtags; `page.updated` consumer |
| 1.16 | Saved collections and generic reporting UI | 2 | Social M15 | Collections CRUD; one `ReportDialog` for posts, comments, users, pages, groups, events and stories, each calling its owning service's report endpoint (1.2, 1.3, 1.9, 1.11, 1.13) |
| 1.17 | Crawler link previews (shared infrastructure) | 2.5 | Social M16 | nginx user-agent map plus internal rewrite; preview images through signed short-lived tokens; public `og:url`; escaped JSON-LD (**cuttable**) |
| | **Step total** | **72** | | |

**Notes on 1.5.** Private post media closes a leak that exists today. Media's `_can_view` lets the owner, or any signed-in user when the asset is public, see a file (`services/media/media_app/services.py`), and every SPA upload passes `visibility="public"` (`frontend/web/src/services/media.ts`). Until 1.5, a friends-only photo, a close-friends story or a private-group image can be fetched by anyone who has its media id, even after an unfriend or a block, and it is served as the original with GPS EXIF. The rollout order matters. First, post returns minted URLs and the SPA uses them. Then `privatize_post_media` runs. Each step is its own release. The media-URL rows in the acceptance tests below are part of step 1; they do not wait for 10.4.

### Dependencies

- The platform gate in [section 5](#5-platform-gate-and-pull-forward-items).
- L.2 (dedicated beat) before 1.8 adds the first new periodic jobs.
- No dependency on later steps. Video posts move to step 5 (decision D1).

### Acceptance tests

- A friend who does not follow the author receives the author's followers-audience post in `/feed/`. After the friendship ends, the item disappears unless the friend also follows.
- With the fan-out cap set to 3 and 10 followers, the author's own feed item always exists.
- A hashtag used only in a friends-audience post never appears in search, autocomplete or trending.
- `PATCH` on a moderator-removed post returns 404, and no `post.updated` outbox row is written.
- Assigning a resolved case returns 409. A second action on the same case returns 409, and exactly one `moderation.actioned` row exists.
- An appeal by anyone but the content owner returns 404; a second appeal returns 409.
- Replying to a reply stores `parent=root` and `reply_to_id=target`. `GET /comments/<root>/replies/` pages without duplicates. Deleting a comment decrements `comment_count`.
- `POST /posts/` with another account's media id returns 400 `media_not_owned`; 11 media ids return 400.
- With `friends_list_visibility=only_me`, the friends and mutual lists return 404 to others. A blocked viewer gets 404 on every list.
- Ranked mode returns the same order for the same fixtures, and page 2 has no duplicates after 5 new posts arrive. Latest mode equals the old chronological order. `GET /feed/` never returns an excerpt for an item the viewer can no longer see.
- A private group's post created with `audience=public` is not searchable, not trending, not recommended and has no crawler preview.
- The search query `اسامة` matches `أسامة`.
- A Facebook crawler fetching a public post gets OG tags with the public `og:url`. A private post gets the generic Tara card. A normal browser gets the SPA.
- **Media URLs (1.5, 1.9, 1.11):** a stranger, a blocked viewer and an ex-friend (after the unfriend) each get 404 for the media of a friends-only photo, a close-friends story and a private-group post, both through `/media/<id>/` and through post's endpoints. The owner and a current friend get a URL that expires. An expired story's media returns 404 to everyone but the author.
- A JPEG uploaded with GPS EXIF is served to other users with no EXIF block. `POST /posts/` with `type=video` returns 400.
- A video upload whose first bytes are HTML fails at completion. A second PUT to the same presigned URL after completion does not change the stored object.
- Reporting a comment, story, group or event that the reporter cannot see returns 404 and writes no outbox row.
- **1.0:** a handler failure in feed lands only in feed's DLQ. A token signed with `INTERNAL_JWT_SECRET` is rejected by identity's role endpoints. An ads serve token signed with the old key is rejected once the 30-minute rollout window has passed. An event published with no bound queue appears in `tara.events.unrouted`. Playwright runs in CI on every PR.

### Risks

- **Size.** This is the largest feature step. Milestone 1.17 can move later without blocking anything. Events (1.13, 1.14) are required by Module 1, but they can move to the end of the step.
- **Broker migration (1.0c).** It changes the live RabbitMQ topology. Rehearse it on a restored broker, keep the rollback script ready, and run it at a quiet hour.
- **Private-media rollout (1.5).** If `privatize_post_media` runs before every client uses minted URLs, images break for everyone except their owners. Ship the two parts as separate releases, and watch 404 rates on `/tara-media/`.
- **Ranking at cold start.** Posts created before 1.7 have no engagement statistics, so ranked mode starts close to chronological.
- **Group read-model lag.** A ban reaches post after the outbox delay. Posting and opening a single private-group post therefore check membership synchronously.
- **Privacy regressions** across many new visibility paths (groups, close friends, stories, events, trending, previews). The single visibility function and the matrix tests are the main defence.
- **Redis memory.** The shared Redis gets `maxmemory` with `noeviction` (1.0h), never an `allkeys-*` policy. Ranking uses `redis-hot` (1.7).

### Deferred, with reasons

| Item | Reason |
|---|---|
| Video in posts | Built once with the video pipeline in step 5 (D1) |
| ML or learned ranking, A/B testing | No engagement data yet; heuristics first |
| Fan-out-on-read for very large accounts | Only needed once follower counts exceed the fan-out cap in practice |
| Story replies to DM, highlights, stickers | Replies need messenger work; the rest are later engagement features |
| OpenSearch with an Arabic analyzer | Postgres trigram plus normalisation comes first |
| Logged-out public pages for posts, groups and events | Needs a product decision on SEO and privacy ([section 21](#21-decisions-needed-from-the-product-owner)); only crawler previews are in scope |

### Verification corrections applied

- QTech's two-level comment reuse is limited to the server-side flattening rule. Tara's `CommentList.vue` already shows "replied to X"; the real defect is replies orphaned by pagination.
- The reaction picker's long-press and hover handling already exists in `PostActions.vue`; that work was removed from 1.4.
- HEIC conversion is medium value (iOS Safari usually converts on upload). The `heic2any` library is large and old, so it must stay a lazy chunk outside the service-worker precache.
- **Blocker fixed:** group and event posts kept a free audience, so a post in a private group marked public would have been indexed, trended and previewed. The server now forces a `group` audience.
- The preview-image route cannot rely on media visibility, because every upload is currently public. It uses signed, short-lived tokens minted only for public, non-removed content.
- **Blocker fixed (critic review):** private content leaked through media until steps 3 and 5. Media access was "owner, or any signed-in user if public", post uploads defaulted to public, and the private-by-default list in 05 did not cover post images, stories or group posts. 1.5 makes content media private and has the owning service mint URLs, and EXIF stripping moves from 3.2 and 5.2 into 1.5.
- Video uploads were unsafe until step 5: there was no signature check for video, the presigned PUT stayed reusable after `complete()`, and `MediaAsset.bytes` kept the declared size. 1.5 closes these and turns off video creation until 5.2.
- `GET /feed/` returned stored snapshots (excerpt and media ids) even after access was revoked. Non-public and explore items are now ids only.
- `/social/<id>/mutual/` also leaked hidden friend lists, and is covered by 1.1 and 1.6.
- `Post.audience` is 12 characters, but `close_friends` is 13; the column is widened in 1.9.
- The moderation `target_type` columns have no choices, so new report target types need serializer changes only, not migrations.
- The events app is named `gatherings` so it does not collide with each service's `events.py` module.

### QTech reuse

- Comment flattening rule from `backend/social/views.py` (`CommentViewSet.perform_create`).
- Media grid and URL-backed viewer from `frontend/src/components/social/PostFeed.vue`, with the swipe direction fixed for RTL.
- HEIC conversion from `frontend/src/utils/heic.js`.
- Arabic normalisation from `backend/core/chatbot.py` (`_norm`), extended with NFKC, zero-width stripping and digit folding.
- Crawler map from `frontend/nginx.conf` and the preview view from `backend/cms/social.py`, with JSON-LD escaping added.
- Versioned cache namespaces from `backend/core/cache.py`, with its typo, race and TTL bugs fixed.
- **Do not port:** `SocialProfileViewSet.posts` (it returns private posts, an IDOR) and the unescaped JSON-LD in `backend/cms/social.py`.

---

## Step 2 — Profiles + notifications

**Goal.** Complete user and business profiles (handles, links, real tabs, privacy lock, business pages, posting as a Page, activity history, an age gate) and turn notifications into one central system with deep links, aggregation, a live list, cross-device read sync, preferences, quiet-hour deferral, new sources and an email digest.

**Owning services.** profile and notification (plus two new realtime bridge handlers), with changes in post, feed, graph, marketplace, media and identity, and payload-only changes in chat and ads. **New services:** none. **New container:** a profile activity consumer on its own queue.

### Milestones

| ID | Milestone | Days | Source | Scope notes |
|---|---|---|---|---|
| 2.1 | Profile API hardening | 3 | Profiles M1 | Fix the 500 on `GET /profile/me/links/`, `/education/` and `/work/`; reject `visibility=custom`, after a data migration maps existing `custom` profiles to `private` (the stricter value; `UserProfile.Visibility.CUSTOM` is a placeholder in `services/profile/profiles/models.py`); validate avatar and cover through media; active-profile manager with both default and base manager names; fix the display-name length mismatch (identity allows 120 characters, profile 80, which makes provisioning fail and dead-letter) |
| 2.2 | Handles, website, typed links | 3.5 | Profiles M2 | One handle registry shared by users and pages, claimed in every creation path; reserved words also at registration; default handles no longer derived from the email address; 14-day cooldown and 30-day hold |
| 2.3 | Profile lock and mention privacy | 2 | Profiles M4 (rest) + Social (mentions) | Author-privacy read model in post (applies only newer events); `/settings/privacy` page for the profile lock, `searchable` (built in 1.6) and mentions; **`mentions_from`** everyone / friends / nobody on `UserProfile`, enforced by post when it resolves mentions (a blocked or disallowed mention is stored as plain text and sends no notification) |
| 2.4 | Professional basics | 2.5 | Professional M1 | Edit work and education; headline and open-to-work; extended work fields |
| 2.5 | Media tabs (photos, listings) | 3 | Profiles M5 | `PostMedia.kind` plus denormalised author and date so the photos tab filters in SQL; marketplace `?seller_id=`; the SPA uses thumbnail and preview variants, with URLs minted by post (1.5), instead of full originals |
| 2.6 | Profile types and business pages | 2.5 | Profiles M7 | Creator type; page avatar and cover; `page.updated` event; `GET /pages/?owner=`; page follower counts from graph |
| 2.7 | Posting as a Page | 4.5 | Professional M9 | Profile internal page-member endpoint; post `as_page_id` with role check; feed fan-out to page followers (paginated, skipping people blocked by the page owner); batch page cards with the route registered before handle routes |
| 2.8 | Activity history | 3.5 | Profiles M8 | Activity log on its own queue and consumer so it cannot delay block events; hides entries on delete and unreact |
| 2.9 | Moderation and lifecycle consumers | 2 | Profiles M9 | Reversible takedown flags; deactivation (reversible, keeps the handle) separated from deletion |
| 2.10 | Profile photo changes as posts | 1.5 | Profiles M10 | Audience follows profile visibility; search skips these posts |
| 2.11 | Profile link previews | 1 | Profiles M11 | Reuses 1.17; opt-in `allow_link_previews` setting |
| 2.12 | Age gate | 2 | new (D12) | Self-declared date of birth or age band at signup in identity; `is_minor` and `age_band` (with `unknown` for accounts created before 2.12) as access-token claims. This is the only way age leaves identity: there is no age event (05 §4.1). Services that decide inside a request read the claims; feed forwards them in its internal ads slot call. Legal text reviewed. |
| 2.13 | Refresh token cookie-only in the SPA | 2 | open item | Identity already sets an httpOnly cookie; the SPA stops keeping the refresh token in `localStorage` (today `frontend/web/src/stores/auth.ts` keeps it through `tokenStore` and posts it in the logout body). For one release identity still accepts a refresh token in the request body, because SPA bundles cached by the service worker keep sending it; the new bundle shows an update prompt; body refresh is removed in the next release. |
| 2.14 | Notification kind registry and deep links | 3 | Notifications M1 | One code registry for category, default channels, aggregation and URL building; structured `data`; in-app click-through |
| 2.15 | Push hygiene and privacy | 2.5 | Notifications M2 | Unsubscribe locally on every logout path (including expired sessions); resume on login; no OS notification while a Tara window is focused; service worker keeps the query and hash of deep links; message-preview opt-out; marketplace `source` field so sellers stop being notified of their own actions |
| 2.16 | Aggregation, live list, read sync, hygiene | 5 | Notifications M3 | Expired aggregates closed before a new row is inserted; actor child table for accurate counts and block cleanup; index on `subject_ref`; `notification.created` carries ids only plus a fetch-by-id endpoint; `message.read` clears chat notifications; block and post-deletion cleanup |
| 2.17 | Preferences v2, quiet-hour deferral, devices, retention | 3.5 | Notifications M4 | Merge-only preference updates validated against the registry; in-app and push decoupled; pushes deferred, not dropped, during quiet hours; device list and revoke; purge jobs |
| 2.18 | New sources | 4 | Notifications M5 | Message reactions (skipping removals), marketplace inquiries, ad review and campaign completion, withdrawn friend requests; inline accept/decline (the item's root element stops being a `<button>`) |
| 2.19 | Email digest | 3.5 | Notifications M6 | Contacts read from identity's internal endpoint instead of copying emails; one-click unsubscribe by `POST`; ar (RTL) and en templates (**cuttable**) |
| | **Step total** | **54.5** | | |

### Dependencies

- Step 1: the media batch lookup and URL minting (1.5), graph counters and settings (1.6) and the crawler infrastructure (1.17).
- Identity changes for 2.12 and 2.13; the notification caller secret on identity (1.0d) for 2.19.
- New event types ship in two releases (section 3.3): the notification consumer goes first, and emission is turned on afterwards.

### Acceptance tests

- `GET /api/v1/profile/me/links/` (and education, work) returns 200 with a `{data}` envelope.
- Registering with an 81–120 character display name creates a profile; nothing reaches the dead-letter queue.
- A handle change inside the cooldown returns 409, a reserved handle 400 and a page's handle 409. The old handle still resolves for 30 days.
- A stranger viewing a locked profile gets an empty `GET /posts/?author_id=` page, and friends-only photos are not in the photos tab.
- An editor of page P posts as P: `author_type=page`. A non-member gets 403. P's followers receive the post, except followers blocked by P's owner.
- 25 reactions on one post produce one unread notification with `actor_count=25`. An unread aggregate older than the window plus a new event creates a new row with no `IntegrityError`.
- After logout with an expired session, the next account on the same browser never receives the previous account's push.
- Clicking a comment notification opens `/posts/<id>?comment=<cid>`, both in the app and from the push notification.
- After signup with a date of birth under 18, the token carries `is_minor=true`. An account created before 2.12 carries `age_band=unknown`.
- With `mentions_from=friends`, a mention by a non-friend creates no mention notification and no link.
- A profile stored with `visibility=custom` before 2.1 is served as private after the migration.
- During the compatibility release, an old cached SPA bundle can still refresh with a body token. After the next release it gets 401 and the update prompt.

### Risks

- Activity-log volume (one row per reaction platform-wide). Retention, indexes and a separate queue limit the impact.
- Privacy read models in post and graph are eventually consistent; tightening privacy takes effect after the outbox delay.
- The graph list response shapes change, so backend and frontend must ship together.
- Default push settings for noisy kinds (reactions, follows) are a product decision.

### Deferred, with reasons

| Item | Reason |
|---|---|
| Videos and reels profile tabs | Need step 5; scheduled in 5.7 (Videos) and 5.8 (Reels) |
| Custom audiences and named friend lists | Close friends covers the main need for far less work |
| Unicode or Arabic handles | Needs a cross-module decision and protection against look-alike characters |
| Native mobile push (APNs/FCM) | There are no native apps |
| SMS, WhatsApp and Telegram channels | Per-message cost and provider onboarding |
| Login and session history in the activity view | Owned by identity, not the profile activity log |

### Verification corrections applied

- Avatars across the app download the full original file, because the SPA ignores media variants. 2.5 switches the SPA to variants.
- On a restricted profile, the SPA still loaded and displayed the friend list. 2.3 and 1.6 close this.
- Privacy settings for relationship lists belong to graph, not profile (D2).
- Activity handlers run on their own queue so a reaction burst cannot delay block propagation.
- Deactivation and deletion were treated the same, which would have destroyed data on a reversible pause.
- **Blocker fixed:** the notification aggregation window conflicted with the partial unique index, so every event after the window would have failed and dead-lettered.
- Notification events would have put message previews on the shared bus; they now carry ids only.
- Logout must unsubscribe the browser locally; a server call alone fails when the session has already expired.
- The email unsubscribe link must not act on `GET` (mail scanners follow links).

### QTech reuse

- Push lifecycle from `frontend/src/mobile/push.js` (never prompt on load, resume on boot, unsubscribe locally first).
- Live list upsert and deep-link builder from `frontend/src/composables/useNotifications.js`.
- Inline-action UX from `frontend/src/components/social/NotificationBell.vue`.
- Synthesised ping from `frontend/src/utils/sound.js`.
- Soft-delete manager pattern from `backend/accounts/managers.py`, keeping both `default_manager_name` and `base_manager_name`.

---

## Step 3 — Messenger

**Goal.** Make chat safe and complete (presence that works, private attachments, edit, delete and forward, unread counts and delivery ticks, Arabic-aware search, message requests and presence privacy), then add 1:1 and group voice and video calls on LiveKit.

**Owning services.** chat (extended), realtime, media and notification. **New containers:** `livekit` (third-party SFU, not a Tara service) and `media-scanner` (clamd, 3.10). **New services:** none.

### Milestones

| ID | Milestone | Days | Source | Scope notes |
|---|---|---|---|---|
| 3.1 | Correctness and security hardening | 4.5 | Messenger M0 | Presence as one Redis sorted set per account (ping refreshes it; closing one tab no longer marks the user offline); WebSocket token moved to the subprotocol header, with `?token=` still accepted for one release because SPA bundles cached by the service worker use it (`services/realtime/realtime/tests/test_ws.py` is updated to cover both), plus an update prompt; typing throttled and not echoed; **a realtime bridge handler drops `conv.<id>` subscriptions on `conversation.member.changed` (removal) and on a block**, so removed members stop receiving typing and message frames; group history starts at join time; race-safe DM creation; blocked marketplace contact becomes a no-op instead of a dead letter; moderation removal emits `message.deleted`; read pointers in REST respect the receipts setting |
| 3.2 | Private attachments, file and video composer | 4.5 | Messenger M1 + Module 5 | Chat uploads private (`privatize_chat_media` for existing ones); chat mints signed URLs after checking membership and that the attachment belongs to the conversation; EXIF stripping, real size and signature checks come from 1.5; rollout in a fixed order so recipients never lose access. **Composer:** file and video attachments (02 found no UI for either): PDF and allowed file types shown as file cards that always download (`Content-Disposition: attachment`) and are blocked while `scan_status` is pending (3.10); chat video plays as uploaded (mp4/webm up to 64 MB, signature-checked, private) |
| 3.3 | Message lifecycle | 4 | Messenger M2 | Edit window and history; delete for me and for everyone (also clears search copies, edit history and notification previews); forward with attachments; reply preview; report; moderation removal reversible on appeal |
| 3.4 | Inbox state, unread counts, delivery | 3 | Messenger M3 | Per-conversation message sequence for unread counts, backfilled one conversation at a time under the conversation row lock that new sends also take (05 §7.3), with a concurrency test; archive, pin and clear; delivered pointer; in groups, read events go only to the reader and the affected senders |
| 3.5 | Search | 2.5 | Messenger M4 | Participant read model; normalised message text with a trigram index |
| 3.6 | Presence privacy, message requests, settings | 3 | Messenger M5 | Presence only for DM peers and friends, revoked on block or removal; message requests also when a non-friend adds someone to a group; local friend-pair read model |
| 3.7 | 1:1 calls on LiveKit | 9 | Messenger M6 | LiveKit container; nginx `/rtc` proxy; server-generated room names; short-lived tokens from the LiveKit SDK; signed webhook read from the raw body; a push-only ring path in notification; a "call ended" push that clears ringing on other devices; TURN on UDP 3478 tested from a mobile network; LiveKit runbook. Re-estimated from 6.5 days: LiveKit, TURN, webhooks and a separate push path are each new to Tara. |
| 3.8 | Group calls | 4 | Messenger M7 | Grid and spotlight layouts, screen share, raise hand over LiveKit data messages, rejoin banner, kick on member removal or block |
| 3.9 | End-to-end and operations | 2 | Messenger M8 | Playwright flows, a WebSocket load script, Grafana dashboards for outbox lag and DLQ depth (on L.1) |
| 3.10 | File scanning | 3 | critic review | `media-scanner` container running clamd (memory budget about 1.2 GB, signature updates through freshclam); a `media.scan` task on its own queue; `scan_status` becomes pending / clean / infected / error (today `services/media/media_app/tasks.py` writes `clean` without any scan); infected files are quarantined (private, never delivered, owner told), and errors retry and then go to manual review. Required to be `clean`: CVs (7.2), ad receipts (6.3), ad creatives (6.4) and chat files. Images and video are re-encoded instead of scanned. If the server cannot spare the memory, the product owner can choose manual review plus forced download instead ([section 21](#21-decisions-needed-from-the-product-owner)); 05 §9.4 then changes to match. |
| | **Step total** | **39.5** | | |

### Dependencies

- Step 2: notification aggregation and clear-on-read (2.16), push (2.15), kind registry (2.14).
- Step 1: media batch lookup, URL minting and upload safety (1.5).
- L.3 (connection sizing) before the new consumers; server memory for `media-scanner` (3.10).
- Host firewall opened for UDP 50000, TCP 7881 and UDP 3478. `Permissions-Policy` (`frontend/web/nginx.conf`, line 42: `geolocation=(), camera=(), microphone=(self)`) changed to allow camera, microphone and screen capture for the site itself.

### Acceptance tests

- Two tabs open, close one: the user is still online. Close both: offline. A socket that only pings for 5 minutes stays online.
- A non-member gets 404 on a chat attachment URL; a private chat upload returns 404 through `/media/<id>/`.
- A member added to a group sees none of the earlier messages.
- Sending `type=system` returns 400; 11 attachments return 400.
- Delete for everyone leaves a tombstone, a reply to it shows a "deleted" preview, and the notification preview is blanked.
- Searching `احمد` finds `أحمد`.
- The call token's room equals the server-generated room name; a room sent by the client is ignored. A blocked pair cannot call. A call nobody answers ends as missed after 45 seconds, exactly once.
- With read receipts turned off, read pointers are absent from REST and from events.
- A member removed from a group conversation, or a user who blocks the other party of a DM, receives no further typing or message frames on an already-open socket.
- An EICAR test file attached in chat ends `infected`, returns 404 to the recipient and is never delivered. A clean PDF downloads as an attachment and never opens inline.
- During the compatibility release, an old SPA bundle connecting with `?token=` still connects and sees the update prompt.

### Risks

- Calls need open UDP/TCP ports and a correct external IP; behind strict NAT, signalling works but media does not. TCP fallback and TURN on UDP 3478 help; TURN over TLS on 443 is deferred.
- Group video bandwidth on a single server. Participants are capped at 16.
- LiveKit webhooks can be lost; a reconcile job and the ringing sweeper limit the damage.
- iOS only delivers Web Push to installed PWAs, so incoming calls on iPhone mostly work only while the app is open.
- Message requests change today's behaviour (non-friend DMs move to a Requests folder) and need a release note.

### Deferred, with reasons

| Item | Reason |
|---|---|
| End-to-end encryption | Conflicts with server-side search, moderation evidence and multi-device history without a key-management design |
| Call recording and transcription | Consent rules, storage cost and an extra heavy container |
| Native push and CallKit | No native apps |
| TURN over TLS on port 443 | Traefik owns 443 on Dokploy; start with UDP 3478 |
| Video transcoding for chat videos | The step-5 pipeline can be reused later. Chat plays mp4/webm up to 64 MB as uploaded, after the 1.5 signature checks, privately and to members only |
| Disappearing messages, polls, stickers, GIF search | Product features that can wait until the core is stable |

### Verification corrections applied

- Read pointers leaked to every member over REST even when receipts would be "off".
- Group read and delivered events would have grown with the square of the group size; they are now targeted.
- A push-only ring needs a separate delivery path; the existing push code requires a notification row.
- Presence for "any shared group" exposed people to strangers; it is limited to DM peers and friends.
- Moderation removal shared `deleted_at` with author deletion and could not be undone; it is now separate.
- LiveKit webhooks use a content type DRF rejects; the receiver is a plain view that reads the raw body.
- Removed members kept their `conv.<id>` subscription (02 §4.4), so they still received typing frames; 3.1 now drops it. Before this change, only 3.8 kicked members, and only from calls.

### QTech reuse

- Presence algorithm from `backend/core/realtime.py`, rebuilt as one sorted set per account (QTech's global counter drifts after a crash).
- LiveKit deployment from `infra/livekit/docker-compose.yml` and its README runbook.
- Room event handling from `frontend/src/composables/useLiveKitCall.js` and the layout from `frontend/src/components/chat/CallOverlay.vue`.
- **Do not port:** the client-chosen room in `call_token` (`backend/chat/views.py`), the unauthenticated `call.*` relay in `backend/core/consumers.py`, or static TURN credentials in the bundle.

---

## Step 4 — Marketplace

**Goal.** Turn the marketplace MVP into a trusted local marketplace: working pre-moderation, photos, correct prices and currencies, category attributes, fast Arabic-aware search with filters and facets, location discovery, business sellers, inquiries and dashboards, reviews, saved-search alerts and comparisons, and a cash/meetup orders foundation.

**Owning services.** marketplace (extended), with changes in chat, moderation, search, notification and media. **New services:** none.

### Milestones

| ID | Milestone | Days | Source | Scope notes |
|---|---|---|---|---|
| 4.1 | Hardening | 3 | Marketplace M0 | Query parameters validated (400 instead of 500); saved list filtered by visibility; `is_saved`; removed listings cannot be edited; `listing.review.requested` opens a pre-review case on its own queue (oldest first); one `listing_visible_to` rule; report visibility; `MARKETPLACE_AUTO_APPROVE` code default false; aliases for the old price parameters |
| 4.2 | Photos and media validation | 2 | Marketplace M1 | Reuses the 1.5 viewer with `?photo=<index>`; up to 10 images; listing media private, with marketplace minting URLs after `listing_visible_to`; only EXIF-stripped variants served. Listing video moves to 5.7 because it needs the step-5 pipeline (D1). |
| 4.3 | Price, currency, condition, category schemas | 3.5 | Marketplace M2 | Price on request vs free; sale price constraint; currency allowlist; per-category attribute schemas with length caps; money formatting that is correct for 3-decimal currencies. **Existing rows first:** `classify_zero_price_listings` moves today's `price=0` listings to "on request" (null), because the old schema could not express either meaning, and lists them so sellers can confirm "free"; `normalise_currencies` upper-cases and maps today's free-text currencies (the model defaults to `USD`, `CreateListingModal.vue` to `EGP`) onto the allow-list, and flags the rest for review, before the check constraint is added `NOT VALID` and then validated |
| 4.4 | Search, filters, sort, facets | 4 | Marketplace M3 | Keyset pagination on (sort key, id); trigram index used by a `contains` lookup; a revision number on listing events against out-of-order delivery; facets adjusted for each viewer's blocks |
| 4.5 | Location discovery | 2.5 | Marketplace M4 | City list; coordinates rounded in the client before sending; bounding box plus distance. Browser geolocation needs `geolocation=(self)` in the `Permissions-Policy` header (`frontend/web/nginx.conf`, line 42, today `geolocation=()`), with a Playwright check; the city picker stays as the fallback. |
| 4.6 | Seller entity, business sellers, storefront | 3.5 | Marketplace M5 | Business listings authorised by page role only (uses 2.7); seller account id hidden from public payloads |
| 4.7 | Inquiries, dashboards, stats, expiry | 4.5 | Marketplace M6 | Chat thread events carry buyer and inquiry ids; crash-safe view-counter flush; listing expiry and renew |
| 4.8 | Ratings and reviews | 3.5 | Marketplace M7 | Eligibility from completed orders or a two-way inquiry; one review per buyer per listing |
| 4.9 | Price-drop alerts and comparisons | 2 | Marketplace M8 | Alerts fanned out in chunks, skipping blocked savers |
| 4.10 | Orders foundation (cash and meetup) and order notifications | 6 | Marketplace M9 + Module 9 | Quantity reserved when the seller accepts; one open request per buyer per listing; mandatory idempotency key; online payment and shipping values reserved but rejected; **`order.requested`, `order.accepted`, `order.declined`, `order.cancelled` and `order.completed` events** (ids and enums only) and matching notification kinds in the 2.14 registry, so buyer and seller are told about every status change |
| 4.11 | Share previews | 1 | Marketplace M10 | Reuses 1.17 |
| 4.12 | Seller terms, age attestation, business disclosure | 1.5 | new | Versioned seller terms with an 18+ attestation; commercial registration and tax id fields for business sellers |
| | **Step total** | **37** | | |

### Dependencies

- Step 2: posting as a Page and the page-member endpoint (2.7), the age gate (2.12), notification kinds (2.18).
- Step 3: chat thread events and the blocked-contact fix (3.1).
- Step 1: the normaliser (1.8), media batch (1.5), crawler infrastructure (1.17).

### Acceptance tests

- `GET /marketplace/listings/?min_price=abc` returns 400, never 500.
- With auto-approve off, publishing creates a pre-review case. Approve makes the listing active; remove makes it rejected, and the seller can edit and resubmit.
- The saved list excludes removed, rejected and pending listings and blocked sellers, ordered by save time.
- Search for `اسكندريه` matches a listing titled `شقة في الإسكندرية`, and the query plan uses the trigram index.
- Sorting by price with 1,050 "price on request" listings pages to the end without repeats.
- A page member with the analyst role cannot create a business listing; an editor can.
- Two concurrent orders for the last unit: one is accepted, the second accept returns 409 `out_of_stock`.
- A crawler fetching an active listing gets OG tags and JSON-LD with an offer only when a price exists; a title containing `</script>` does not break out of the script tag.
- After the 4.3 migration, no listing has `price=0` unless its seller confirmed "free", and every listing's currency is in the allow-list or flagged for review.
- When the seller accepts an order, the buyer gets an order notification with a deep link to the order. A decline or cancel notifies the other party.
- On the location page, the browser's location prompt appears (the `Permissions-Policy` allows it), and the coordinates sent are rounded.

### Risks

- Cross-currency results: price filters and sorts work within one currency only.
- Review collusion (a seller naming a friend as the buyer). Eligibility rules reduce it but do not remove it.
- Moderation workload: with pre-review on, every new listing waits for a moderator.
- Cash and meetup orders without escrow invite no-shows and scams; a safety notice and dispute status are the only protection.
- Prohibited items differ between Egypt and Gulf countries; a written prohibited-items policy is needed before launch.

### Deferred, with reasons

| Item | Reason |
|---|---|
| Online payments and escrow (Paymob, Fawry, Tap, Stripe) | Needs a legal merchant entity, seller KYC, PCI scope, webhooks and refunds |
| Shipping integrations | Needs carrier contracts, labels and tracking webhooks |
| Currency conversion for cross-currency sorting | Needs a rates source and gives hard-to-explain results |
| Saved searches with new-listing alerts | Wait until the filter contract (4.4) is stable |
| Sponsored listings | Built by ads in step 6 |
| Listing video | Needs the step-5 pipeline (D1); built in 5.7 |
| Team inbox for business pages | Chat conversations hold one seller account today |
| Seller KYC and verification badges | Depends on identity phone verification and page verification |
| Anonymous browsing | Needs a separate privacy and SEO decision |

### Verification corrections applied

- **Blocker fixed:** the crawler preview put user titles into JSON-LD unescaped, an HTML-injection path reachable with a spoofed user agent.
- Cursor pagination on shared sort keys repeats pages after 1,000 equal values; keyset pagination on (key, id) replaces it.
- `icontains` does not use a plain trigram index; normalised text with `contains` does.
- Business listings authorised by `seller_id` let a removed page editor keep control; authorisation is by current page role.
- Phone photos carry GPS EXIF, which undid the coordinate rounding.
- Production env already runs with auto-approve off, so the pre-review gap is live on any Dokploy deploy (see [section 5.4](#54-operational-note)).

### QTech reuse

- Price semantics, effective-price ordering and the tolerant category filter from `backend/cms/models.py` and `backend/cms/views.py`.
- `PriceTag.vue`, `FilterChip.vue` and `SortSheet.vue` from `frontend/src/components/ui/`, ported to TypeScript with i18n.
- The settings-catalogue validator from `backend/cms/chrome.py`, extended with numbers, bounds and required fields.
- **Do not port:** QTech `money.js` rounding for fractional 3-decimal amounts, the invoice numbering in `backend/billing/models.py`, or the JSON-LD in `backend/cms/social.py`.

---

## Step 5 — Video + reels

**Goal.** One media video pipeline that serves three products: video in normal posts, long-form video (YouTube-like: watch page, channel tab, playlists, history, discovery, creator studio) and reels (TikTok-like vertical short video with For You and Following feeds, sounds and captions).

**Owning services.**

- **media:** ingest, the ffmpeg transcoder on its own queue and container, posters, progressive MP4, HLS delivery.
- **post:** new apps `videos` and `reels`; Post stays the single authority for audience, deletion and moderation.
- **feed:** reels feeds and ranking, the unified watch telemetry, creator analytics.
- **search, notification, moderation:** consumers.

**New containers:** `media-transcoder` (1.5 GB, 2 vCPU, concurrency 1) and `media-consumer`. **New services:** none.

### Milestones

| ID | Milestone | Days | Source | Scope notes |
|---|---|---|---|---|
| 5.1 | Edge wiring and prerequisites | 2.5 | Video M0 + Reels M0 | Routes `/api/v1/videos`, `/playlists`, `/library`, `/studio` and `/reels` to post; CSP `worker-src 'self' blob:`; a shared view-token helper in `libs/tara_common`; restricted MinIO user; Traefik timeout checked for large uploads |
| 5.2 | Shared video pipeline | 13 | Video M1 + Reels M1 + Social M4 (D1) | Re-estimated from 9 days: HDR tone-mapping, ffmpeg hardening and quotas are each a multi-day job. Accepts `video/quicktime` (the signature, size and ETag checks already exist from 1.5); per-purpose caps and daily quota; video post creation turned back on. The transcoder runs with a minimal environment (no platform-wide internal secret, a scoped storage user), forced demuxers and protocol whitelists, time and memory limits, non-root. Outputs: posters, 720p/480p faststart MP4, audio track, waveform; HDR tone-mapping; metadata stripped. At most 3 attempts per file. Non-owners never receive the original upload. |
| 5.3 | HLS ladder and secure playback | 5 | Video M2 | Token-authorised playlists; segment URLs presigned per time bucket (or single-file renditions) so caching stays safe; access log off for the playlist path; media consumes `video.removed` and blocks playback |
| 5.4 | Video domain in post | 5 | Video M3 | `videos` app; Post is the only authority for audience, deletion and moderation; `media_id` unique for ever; handles media finishing before the Video row exists; legacy post edit and delete refuse video posts; `post.restored` event |
| 5.5 | Reel domain in post | 4 | Reels M2 | `reels` app; `publish_state`; author denormalised on Reel; unique media id; reconcile job; reels show in followers' feeds at their publish time |
| 5.6 | Unified watch telemetry | 5 | Video M5 + Reels M6 (D8) | Feed-owned; beacons authenticated by the view token so `sendBeacon` works; per-account throttle (carrier NAT would break per-IP limits); capped Redis stream; exactly-once rollups with a stored high-water mark; one view per viewer per day in SQL |
| 5.7 | Long-form frontend, video in posts, profile Videos tab, listing video | 8.5 | Video M4 + Social M4 + Profiles (Module 8) + Marketplace M1 | Watch page; upload wizard with progress; studio list; post composer uploads video through `/videos/`; feed video card; hls.js lazy-loaded, native HLS on Safari; scrubber correct in RTL; **Videos tab** on user profiles and Pages, filtered by the viewer's visibility in SQL; **listing video** (one per listing) through the pipeline, with marketplace checking the Video's ready state |
| 5.8 | Reels viewer, composer and profile Reels tab | 10 | Reels M4 + M5 + Profiles (Module 8) | Snap pager with at most 3 mounted videos; muted autoplay; double-tap like; URL-backed comment and share sheets; composer with cover, audience and HEIC covers; **Reels tab** on user profiles and Pages, opening the pager at the chosen reel |
| 5.9 | Library | 3.5 | Video M5 (rest) | History (pause, clear), playlists, watch later, liked and saved videos; one saved-item type per video |
| 5.10 | Video discovery | 5.5 | Video M6 | Trending snapshots; recommended; related (normalised tags); discovery lists public-only; graph batch relationships for the rest |
| 5.11 | Reels feeds and ranking v1 | 7 | Reels M3 + M7 | Follow and block read models with tombstones; author eligibility (profile privacy, moderation restrictions); minors get a non-personalised feed; backfills pull from internal endpoints instead of replaying user-action events |
| 5.12 | Unified creator studio analytics | 6 | Video M7 + Reels M6 (UI) | Views, watch time, retention, sources and devices; breakdowns hidden below 10 viewers; regions only from a trusted edge header |
| 5.13 | Sounds | 5 | Reels M8 | Original sounds copied to their own asset so deleting a reel does not break them; admin library with licence fields; reuse off by default. Required by Module 4 (reels music and audio). |
| 5.14 | Captions | 2 | Reels M9 | WebVTT/SRT upload and a CC toggle. Required by Module 4. |
| 5.15 | Safety, moderation, previews, lifecycle | 5 | Video M8 + Reels M10 | Moderator preview with a frame strip; removal revokes playback; copyright takedown process; resumable multipart upload; purge jobs; previews for public videos and reels (reusing 1.17) |
| 5.16 | Delivery hardening and load test | 3 | Reels M11 | Range requests, URL-expiry resume, low-end Android memory check, k6 load test, transcode throughput on the target server, runbook |
| | **Step total** | **90** | | |

### Dependencies

- Steps 1–2: posts, comments, reactions, feed, graph batch relationships, notification kinds, the age gate, and the 1.5 upload checks.
- Step 4 for listing video (5.7).
- The restricted MinIO user and the storage decision ([section 5.1](#51-gate-before-step-1-owner-task-in-parallel-with-week-1)).
- Server capacity for the transcoder, and `redis-hot` sized for telemetry (decision 13 in [section 21](#21-decisions-needed-from-the-product-owner)).

### Acceptance tests

- An HTML file uploaded as `video/mp4` fails at upload completion and its object is deleted.
- A generated 3-second 640×360 clip ends ready with 240p and 360p renditions (no upscaling), posters with real dimensions, the right duration and no location metadata.
- A source longer than the duration limit ends failed with `too_long`; the scratch directory is empty afterwards.
- A tampered or expired playlist token returns 401/404; a moderator-removed video stops playing for viewers within the playlist cache window.
- Creating a Video with another account's media id returns 404; a second Video with the same media id returns 409.
- Replaying `media.processed` twice publishes exactly once: one `post.created` and one publish event.
- A followers-only video returns 404 on the watch and playback endpoints for a non-follower, and for a blocked viewer even when public.
- A watch session counts one view after 30 seconds of real watch time; a second session the same day does not; the owner's own views never count; a claimed 10-minute jump in 15 seconds is clamped.
- Re-running the telemetry rollup after a crash before acknowledgement does not double-count.
- For You never returns the viewer's own reels, blocked authors, "not interested" authors or sounds, removed reels, or reels already seen.
- A minor's For You is not personalised.
- The profile Videos and Reels tabs show a followers-only video or reel to a follower, and never to a stranger or a blocked viewer.
- Playwright (ar and en): upload a clip, see progress, get the "your video is live" notification, play it, react, comment, add to watch later, find it in history with a resume position.

### Risks

- **CPU on one server.** Transcoding saturates cores. Concurrency 1, a 720p default ceiling, daily quotas and queue-depth alerts limit the impact; a backlog is likely at launch.
- **Storage and egress.** Originals plus renditions take about 2–2.5× the source size. Originals are deleted after transcoding (retention decision needed).
- **RabbitMQ consumer timeout** (30 minutes by default) on long jobs: each rendition is a separate chain step, and the timeout is raised for the transcode queue.
- **Malicious media and ffmpeg CVEs:** hardening reduces but does not remove this.
- **Copyright and harmful content:** no fingerprinting; a takedown process and moderator preview must exist before uploads open publicly.
- **Redis telemetry footprint:** capped stream, short HyperLogLog retention and its own Redis if needed.

### Deferred, with reasons

| Item | Reason |
|---|---|
| Live streaming | Needs LiveKit ingress/egress, low-latency HLS and real-time moderation |
| Monetisation (ads in video, creator revenue) | No payments or KYC |
| Unlisted videos | A new audience value that every service must honour |
| Page channels | Posting as a Page (2.7) makes it possible later; kept out to keep this step bounded |
| ML or collaborative recommendations | Not enough data; heuristic v1 produces the training signals |
| Automatic captions (speech-to-text) | CPU or GPU cost on the single server |
| Content ID and audio fingerprinting | Needs a vendor or dataset |
| Duets, effects, in-app camera, green screen | Heavy client work |
| CDN and edge caching of segments | Add after measuring load or moving storage to R2/S3 |
| Licensed music catalogue | Needs licensing contracts |
| Logged-out viewing of public videos | Product decision ([section 21](#21-decisions-needed-from-the-product-owner)) |

### Verification corrections applied

- **Blocker fixed:** existing media endpoints serve the original upload (with GPS, at full size) of every public asset to any user. EXIF stripping and private content media land in 1.5; 5.2 makes the response purpose-aware for video.
- **Blocker fixed:** backfilling read models by re-emitting `user.followed` and `reel.published` would have re-sent notifications for every existing follow and reel.
- The transcoder would have inherited platform-wide secrets; it now has a minimal environment.
- Video and Post would have been two sources of truth for audience and deletion; Post is the only one.
- A Video row could be created after media had finished processing, leaving it stuck in "processing"; this is handled.
- Removing a video did not stop playback for hours; media now blocks playback on removal.
- Beacons throttled per IP would have dropped real traffic behind mobile-carrier NAT.
- One telemetry pipeline instead of two (D8).
- The QTech poster rule skipped a rendition equal to the source width; ported as "strictly smaller".

### QTech reuse

- Visibility-clock watch time from `frontend/src/composables/useVisitorTracking.js` and the clamping rules from `backend/core/tracking.py`.
- Traffic-source resolver from `backend/core/attribution.py`.
- Image safety rules from `backend/core/images.py`, and the poster image contract from `frontend/src/components/ui/SmartImage.vue`.
- Pull-to-refresh from `frontend/src/mobile/components/PullToRefresh.vue` and the swipe maths from `frontend/src/mobile/composables/useSwipeBack.js`.
- CSV export from `backend/core/export.py`, with a formula-injection guard added.

---

## Step 6 — Ads manager

**Goal.** A Meta-like ads manager that never serves a paid campaign without approval and verified payment: correct spend accounting, personal and business ad accounts, prepaid funding with manual verification, a campaign builder with budgets and schedules, image ads, video and reel ads, sponsored posts and promoted listings, targeting, insights, fraud protection and conversions.

**Owning services.** ads (extended), with internal endpoints added in post, marketplace and profile, and consumers in notification and moderation. Country lookup lives inside ads. **New container:** `ads-consumer`. **New services:** none.

### Milestones

| ID | Milestone | Days | Source | Scope notes |
|---|---|---|---|---|
| 6.1 | Correctness and hardening | 3.5 | Ads M1 | State re-checked under the row lock; charges clamped to the remaining budget; spend accrued in integer micro-units; one billing event per ad set; a click is billed only after its impression; default throttles merged, internal slot views unthrottled; campaign detail endpoint; no account auto-created on GET. **E2E rewrite:** `frontend/web/e2e/growth.spec.ts` assumes that opening `/ads` creates the advertiser account; the spec creates it explicitly. |
| 6.2 | Personal and business ad accounts | 4 | Ads M2 | One `actor_role()` check in every route, legacy routes included; page-role read model with tombstones; synchronous role check for money operations |
| 6.3 | Prepaid funding, payment verification, state machine | 5.5 | Ads M3 | Manual top-up requests with receipts that must be scan-clean (3.10); a **`finance` role** added to identity's `AccountRole` (today admin, moderator, ad_reviewer and analyst in `services/identity/identity/models.py`; a choices-only `AlterField`) and to the admin role UI, with separation of duties (a finance user cannot approve their own top-up); spend settled for closed days (no duplicate-reference failures); explicit status transitions. The serving switch from 1.0 is turned on only after this ships. **E2E rewrite:** `growth.spec.ts` expects a campaign to go active without funding; the spec now tops up and has the top-up verified first. |
| 6.4 | Campaign builder v2 | 6 | Ads M4 | Objectives, daily and lifetime budgets, pacing, schedules, image creatives; revisions keep a lineage id so caps and stats survive edits; discarded revisions kept, not deleted |
| 6.5 | Sponsored posts and promoted listings | 5 | Ads M5 | Post and marketplace internal endpoints; edits and restores send the creative back to review |
| 6.6 | Targeting v1 and viewer controls | 5 | Ads M6 | Country computed inside ads from a trusted proxy chain; language; explicit interest topics; "why this ad", hide advertiser, report ad |
| 6.7 | Insights, reach, reports | 5 | Ads M7 | Daily stats; reach registers flushed to Postgres; CSV export with formula guard; monthly statements |
| 6.8 | Fraud, invalid traffic, policy | 5.5 | Ads M8 | Bot and self-impression exclusion; per-viewer caps; **account-level thresholds for billable events** (account age and a trust score, so fresh or sock-puppet accounts cannot bill clicks); refunds for invalid spend; special categories with a second review step; political ads refused. **E2E rewrite:** `growth.spec.ts` clicks the card without a viewability gate; the spec now waits for a visible impression first. |
| 6.9 | Conversions and attribution | 4 | Ads M9 | In-platform conversions plus an API keyed per advertiser; click lookups scoped to the key's own advertiser |
| 6.10 | Age rules and minors, age-band targeting behind a flag | 3 | Ads M10 | Uses the 2.12 claims, which feed forwards in the slot call; restricted categories off for minors and unknown ages; never target under-18s. **Age-band targeting** (18–24, 25–34, 35–44, 45+) ships behind `ADS_AGE_TARGETING_ENABLED`, off until legal sign-off (decision 15 in [section 21](#21-decisions-needed-from-the-product-owner)); while the flag is off, age fields in an ad set return 400. |
| 6.11 | Restricted verticals and landing-page checks | 1 | new | Per-country restricted categories; redirect-chain resolution for landing URLs |
| 6.12 | Video and reel ads | 4.5 | Ads design (format enums already reserved) + critic review | Video creatives through the 5.2 pipeline; video viewability from 5.6 telemetry (billed impression after 2 s at 50% visible); a reel placement in the reels feed (5.11) with frequency caps; review shows the 5.15 frame strip. Built last in step 6 because it needs 5.2, 5.6 and 5.11. |
| | **Step total** | **52** | | |

### Dependencies

- Step 2: the page-member endpoint (2.7) and the age gate (2.12); notification kinds for ads (2.18).
- Step 3: file scanning (3.10) for receipts and creatives.
- Step 4: a marketplace internal listing endpoint (added in 6.5).
- Step 5, for 6.12 only: the video pipeline (5.2), telemetry (5.6) and the reels feed (5.11).
- Media must expose `scan_status` to internal callers.
- Suspension of advertisers whose Tara account is suspended needs step 8 (8.5).

### Acceptance tests

- Submitting a campaign on an unverified account returns 409 `payment_unverified`; without enough balance, 409 `insufficient_funds`. Balance and reservation are unchanged in both cases.
- A finance user cannot approve their own top-up.
- Lifetime budget 100 with clicks at 30: four billable clicks leave `spent == 100.0000` and the campaign completes. 50 concurrent clicks at the budget edge still keep spend within the reservation.
- Running the settlement job twice on the same day writes the correct total, with no duplicate-reference error.
- A click with no spent impression, an impression visible for under one second, or a bot user agent debits nothing.
- An analyst on a business account can read insights but gets 403 on writes; a non-member gets 404.
- Editing a sponsored post sends the creative back to review; it stops serving until approved.
- A country-targeted ad set is never served outside its countries.
- With `ADS_AGE_TARGETING_ENABLED` off, an ad set with age bands returns 400. With it on, an age-band ad set never matches a minor or an `unknown` age.
- A click from an account below the account-age or trust threshold is recorded with `is_valid=false` and debits nothing.
- A video ad is billed only after 2 s at 50% visible; a reel ad never appears in a minor's reels feed when its category is restricted.

### Risks

- Manual payment verification is operational work and exposed to fake receipts; separation of duties, audit and the prepaid model limit the exposure.
- Legal: targeting, minors and personalised ads fall under Egypt PDPL (Law 151/2020), KSA PDPL and UAE PDPL; legal review before personalisation is on by default.
- Monthly statements are not tax invoices; larger business advertisers will ask for them.
- Hot-row contention on busy campaigns at scale.

### Deferred, with reasons

| Item | Reason |
|---|---|
| Real payment gateway (Paymob, Fawry, Stripe, 3-D Secure, chargebacks) | No payments module or PCI decision; top-ups are designed so a gateway can produce credits later |
| Tax invoices (Egyptian e-invoicing, Gulf VAT) and postpaid credit | Needs finance, legal and an invoicing provider |
| Custom audiences, lookalikes, tracking pixels | Privacy and consent problems, and CSP changes |
| Behavioural interest inference | Profiling needs a consent decision; explicit topics only |
| Audience size estimates | Small counts could de-anonymise users |
| Real-time auctions and ML click prediction | Ranking by expected cost per thousand is enough at current inventory |
| City and radius targeting | Country only, so no location is stored |
| Political and social-issue ads | Need verified identity, ad libraries and per-country rules |

### Verification corrections applied

- **Blocker fixed:** hourly settlement used a reference that is unique per campaign-day, so the second run each day would have failed and spend would never be debited.
- Per-impression spend rounded to 4 decimals lost or over-charged money; accrual moves to integer micro-units.
- Merging default throttles would have throttled the internal slot endpoint for the whole platform from one feed IP.
- Legacy owner checks would have kept a removed page admin in control of a business account.
- Ads served unfunded campaigns until funding existed; the serving switch (1.0) closes that gap from week 1.
- Promoted-listing edits bypassed re-review.
- Serve tokens were keyed from the platform-wide internal secret, so any service could forge billable events; 1.0e gives them an ads-only secret.
- Video and reel ads were deferred "until step 5 playback is stable", but step 6 is built after step 5 and Module 6 requires them; they are now 6.12.

### QTech reuse

- Viewability clock from `frontend/src/composables/useVisitorTracking.js`.
- Bot marker list from `backend/core/attribution.py`.
- GeoIP reader with hot reload from `backend/core/geo.py`, and the download-validate-swap from `backend/core/management/commands/update_geoip.py`.
- Live/pending revision semantics from `backend/cms/views.py` (`PageViewSet`).

---

## Step 7 — Professional

**Goal.** A LinkedIn-like professional layer on top of profiles and pages: skills and certifications, CV upload, company pages with followers, job listings and search, applications, a recruiter dashboard, interviews, endorsements, employment verification and job alerts.

**Owning services.** profile (new `careers` app in `profile_db`), media, graph (follower counts), search, notification, moderation. **New services:** none.

### Milestones

| ID | Milestone | Days | Source | Scope notes |
|---|---|---|---|---|
| 7.1 | Skills and certifications | 3 | Professional M2 | Skill catalogue with a key normaliser that keeps `+ # . / -`; alias table for curated merges; certifications with https-only credential URLs |
| 7.2 | CV upload | 2.5 | Professional M3 | PDF only, up to 5 MB checked on the stored object; PDFs with scripts or embedded files rejected; recruiters can download a CV only once its `scan_status` is `clean` (3.10); download disposition with correct Arabic filenames; media headers applied through a shared nginx snippet |
| 7.3 | Company pages | 3 | Professional M4 | Company fields editable by owner and admin only; verified badge cleared when the name, handle or website changes; page-creation throttle; follower counts from graph (D5) |
| 7.4 | Job postings and discovery | 5 | Professional M5 | Draft, publish, pause, close, expire; jobs search with Arabic normalisation; posting-policy flagger for protected attributes and fee requests; open-job cap per owner account across all their unverified pages |
| 7.5 | Applications | 4.5 | Professional M6 | Idempotent apply with a race-safe savepoint; consent recorded with version, time and shared fields; withdrawing revokes CV and profile access at once; applicant data export |
| 7.6 | Recruiter dashboard | 3.5 | Professional M7 | Pipeline board (stage select first, drag optional); applicant drawer; message through a normal DM |
| 7.7 | Interviews and feedback | 3 | Professional M8 | Meeting URL and time zone; panelists restricted to page members, with their own limited view |
| 7.8 | Endorsements and employment verification | 3 | Professional M10 | Endorsements between friends only; employment confirmed only by verified company pages, never by the requester |
| 7.9 | Job alerts and retention | 2.5 | Professional M11 | Daily and weekly digests; applications anonymised after retention; deleted CVs purged |
| 7.10 | Page moderation and recruiter invitations | 1.5 | new (D13) | A removed page closes its jobs and leaves search; recruiter roles take effect only after the invitee accepts |
| | **Step total** | **31.5** | | |

### Dependencies

- Step 2: pages, posting as a Page and the page-member endpoint (2.7), professional basics (2.4), age gate (2.12).
- Step 1: graph counters (1.6), the normaliser (1.8).
- Step 3: private file handling (3.2) for the download headers, and file scanning (3.10) so recruiters only receive `clean` CVs.

### Acceptance tests

- Adding `مُهندس برمجيات` and then `مهندس برمجيات` creates one skill; C, C# and C++ stay three skills.
- A CV declared as 1 KB but stored as 20 MB is rejected; a PDF with JavaScript is rejected.
- Renaming a verified company page clears its verified badge.
- Applying twice returns 201, then 200 with `already_applied` and the same id; concurrent inserts produce one row.
- After the applicant withdraws, the recruiter's CV link returns 404.
- A page owner cannot verify their own work entry, and an unverified page cannot verify anyone.
- A removed company page closes all its open jobs, and they disappear from job search.
- Playwright (ar and en): owner adds a recruiter, the recruiter accepts the invitation, publishes a job; a user uploads a CV and applies; the recruiter schedules an interview; the applicant sees "interviewing".

### Risks

- Fake companies and job scams are common in Egypt and the Gulf; admin verification is manual work.
- Applicant personal data is stored in `profile_db`; retention and consent records are needed.
- Discriminatory postings (nationality, gender, religion) are common in the region; the flagger only catches obvious cases.
- Interview times across Egypt (with daylight saving) and Gulf countries (without): store UTC plus the time zone.

### Deferred, with reasons

| Item | Reason |
|---|---|
| Paid job promotion | Needs payments |
| External "apply on website" links | A phishing vector; later for verified pages only |
| Offer letters and e-signature | Sensitive legal and financial documents |
| Video interviews | Could reuse the step-3 LiveKit setup later; kept out to keep the step small |
| Talent search and recruiter messaging tiers | Needs verified recruiter identity and probably paid tiers |
| AI CV parsing and matching | Model cost, weak Arabic parsing, personal data sent to a model |
| Long-form articles | Post has no long-form type |

### Verification corrections applied

- **Blocker fixed:** a page owner could approve their own employment claim and get a "verified" badge.
- The CV size cap trusted the declared size.
- Recruiters would have downloaded unscanned PDFs.
- The skill normaliser would have merged C, C# and C++.
- Fake company pages could be reported but nothing enforced the outcome.
- Adding headers inside the `/tara-media/` location would have dropped every inherited security header.

### QTech reuse

- Applicant-tracking model shape (stages, panel feedback) from `backend/hr/models.py`, with a transition table added.
- Public job board flow from `backend/hr/careers.py` and `frontend/src/pages/public/CareersPage.vue`, without the email-keyed candidate overwrite.
- Pipeline layout from `frontend/src/pages/app/modules/HrRecruitment.vue`.
- Field stripping by viewer from `backend/hr/serializers.py`.

---

## Step 8 — Admin dashboard

**Goal.** A staff console and trust-and-safety system: one audit trail, moderation cases with evidence, suspensions and feature restrictions that every service enforces, user and page management, appeals that really reverse decisions, blocked terms and domains, content policies, platform statistics, fine-grained staff capabilities and system settings.

**Owning services.** admin (console, audit, statistics, settings, flags, health), moderation (cases, evidence, appeals, policies, blocklists), identity (restrictions, capabilities), plus consumers in post, profile, chat, graph, search, ads, realtime and notification. **New containers:** `admin-worker`, `admin-consumer`, `identity-consumer`. **New services:** none.

### Milestones

| ID | Milestone | Days | Source | Scope notes |
|---|---|---|---|---|
| 8.1 | Event plumbing, capability registry, unified audit | 4.5 | Admin M1 | Outbox and consumer for admin; capability registry in `libs/tara_common`; audit read API and export; system actors allowed; request id and region set by the edge, not by clients |
| 8.2 | Case evidence and triage | 5 | Admin M2 | Content snapshots from each service's internal target endpoint; keyset triage order; media on legal hold while a case or appeal is open; a manual path for severe harm |
| 8.3 | Report intake completion | 1 | Admin M3 | Listing report visibility; listing pre-review cases already come from 4.1 |
| 8.4 | Account suspensions and restrictions | 5.5 | Admin M4 | One synchronous path from a moderation action into identity, in this order: moderation's view runs with `non_atomic_requests`, pre-generates the action id and calls identity's suspend endpoint **first** with an idempotency key derived from the case id and that action id (moderation is a named caller under 1.0d); identity applies the suspension once per key and revokes sessions and refresh tokens in its own transaction; moderation then commits the action, the case resolution and an outbox row in one transaction; a reconcile job compares identity's active suspensions with resolved cases and repairs either side. 05 §4.1 states the same rule. A dedicated appeal token class; Django admin fields for status and staff flags made read-only |
| 8.5 | Suspension propagation | 3.5 | Admin M5 | Search hides suspended owners without deleting documents; chat, graph, ads (pause campaigns) and realtime consumers; a suspended page hides its own posts |
| 8.6 | User management console | 3.5 | Admin M6 | Search and detail; staff access to personal data is audited |
| 8.7 | Business page management | 1.5 | Admin M7 | Console UI on top of 7.10 |
| 8.8 | Appeals end-to-end | 4 | Admin M8 | A reversal map per action and target type; appeal state guard; four-eyes resolution; decision notices |
| 8.9 | Blocked content | 4 | Admin M9 | Matcher in `libs/tara_common` evaluated at write time so "hold" happens before publication; held posts hidden from everyone but the author; normaliser hardened against evasion |
| 8.10 | Content policies | 1.5 | Admin M10 | Versioned ar/en community standards |
| 8.11 | Platform statistics | 3.5 | Admin M11 | Counters updated in the consumer transaction; health polled by a beat task, not per request |
| 8.12 | Capability matrix | 3.5 | Admin M12 | Namespaced capability keys in the token; matrix editor; the raw email removed from access tokens |
| 8.13 | System settings | 2 | Admin M13 | Schema-validated settings with a public subset (for example a site banner) |
| 8.14 | Immediate access-token revocation | 1.5 | Admin M14 | Optional Redis denylist |
| | **Step total** | **44.5** | | |

### Dependencies

- Every earlier step: each service exposes an internal target endpoint for evidence, and each consumes the suspension events.
- Staff two-factor authentication (L.4; only a scaffold exists today) before more than one admin is granted.
- Per-service DLQ routing (1.0c) and alerting (L.1), because suspension fans out to many consumers.

### Acceptance tests

- A moderator with the suspend capability cannot suspend an account that holds any staff role; nobody can act on an admin account or on themselves.
- Suspending an account revokes every session and refresh token, closes its sockets (code 4403), hides its profile and posts and pauses its ad campaigns.
- A suspended user can log in only to an appeal-only view; the appeal token is rejected by every other endpoint.
- Overturning a removal restores the content for each target type: post, comment, message, listing, page and user.
- A blocked-term "hold" rule keeps the post out of feeds, search and notifications from the start.
- The same event delivered twice to the admin consumer creates one audit row; actions by the system (expiry jobs) are audited without errors.
- A crafted `X-Geo-Region` or `X-Request-Id` header from a client does not reach the audit log.
- If moderation's commit fails after identity has suspended, a retry with the same idempotency key does not create a second suspension, and the reconcile job links or lifts the orphan.

### Risks

- Suspension and removal fan out to many consumers; a dead-lettered consumer leaves content visible in one place. Per-service DLQ routing (1.0c), DLQ alerts (L.1) and replay are the mitigation.
- Privacy: moderators reading reported private messages needs a written policy, retention limits and access audit.
- Arabic dialect variation causes false positives in blocked terms; start with "flag" and use "hold" only for high-confidence terms.
- About 640 MB more memory for the three new containers.

### Deferred, with reasons

| Item | Reason |
|---|---|
| Account deletion and erasure across all services | No longer deferred: scheduled as L.5 ([section 5.3](#53-launch-hardening-track-l)), after this step and before public launch |
| ML classifiers | Need vendor contracts, legal agreements and GPU or hosted APIs. CSAM hash matching is no longer deferred: it is L.6 |
| Shadow banning | Opaque to users and conflicts with decision notices |
| Live queue push over WebSocket | 15-second polling that pauses on hidden tabs is enough at this scale |
| Transparency reports and a data warehouse | Daily metrics are enough for now |
| Separate secrets for every internal call | Identity's privileged endpoints get caller-specific secrets in 1.0d, and ads serve tokens get their own secret in 1.0e. The remaining internal endpoints are read-only and stay on the shared secret for now |

### Verification corrections applied

- Overturned appeals always emitted "approve", which did nothing for most target types; a reversal map replaces it.
- There were two suspension paths with different authorisation; one synchronous path remains.
- The "pre-publication hold" actually ran after publication; matching moves to write time.
- Held (pending) posts were still visible, because the visibility check only excluded removed posts.
- Deleting search documents on suspension and re-indexing on reinstatement lost older posts; hiding by owner replaces it.
- Audit metadata came from client-controlled headers.
- Django admin let staff change account status and staff flags, bypassing all of this.
- The suspension path was described as "inside the case transaction", which `ATOMIC_REQUESTS=True` cannot do safely; 8.4 calls identity first with an idempotency key and reconciles.

### QTech reuse

- Permission precedence and the matrix editor rules from `backend/access/services.py` and `frontend/src/pages/app/modules/AdminPermissions.vue`.
- Audit index set from `backend/core/models.py` (`AuditLog`) and the list layout from `frontend/src/pages/app/modules/AdminAudit.vue`.
- Polling that pauses on hidden tabs from `frontend/src/pages/app/modules/AdminMonitor.vue`.
- **Do not port:** QTech's reset-link action (it lets HR take over a manager account) or its email-keyed failed-login grouping.

---

## Step 9 — Design system pass

**Goal.** Make the ten modules read as one product. The brand system already exists (`tailwind.config.js`, `src/style.css`, `src/components/brand/TaraLogo.vue`, `docs/design/brand.md`). Since the definition of done (section 3.2) already requires brand tokens and an axe check in every milestone's Playwright flow, this step consolidates and enforces; it does not retrofit every screen. It covers Arabic and English, light and dark.

**Owning services.** `frontend/web`. **New services:** none.

### Milestones

| ID | Milestone | Days | Scope notes |
|---|---|---|---|
| 9.1 | Token and component audit | 3 | No raw colour literals outside the token files (a lint rule enforces it); ported QTech components (call overlay, price tag, charts) moved to brand tokens; dark-mode check on every route of the ten modules; `docs/design/brand.md` updated |
| 9.2 | RTL and i18n pass | 3 | Gesture and arrow directions (photo viewer, reels pager, video scrubber, pipeline board); logical properties; Arabic plural forms; dates, numbers and currencies through `Intl`; `dir="auto"` on user text |
| 9.3 | Accessibility pass | 3 | axe-core in Playwright on every route (the per-milestone checks already cover the main flows); dialogs with roles and focus traps; keyboard paths in the pager, viewer, board and calls; alt text and captions; reduced-motion support; contrast |
| 9.4 | Shared primitives consolidation | 2 | Media grid and viewer, video player, report dialog, price tag, insights chart, empty/error/loading states: one documented component each |
| 9.5 | Performance pass | 2.5 | Bundle budgets in CI; hls.js, livekit-client and heic2any loaded lazily and excluded from the service-worker precache; image variants everywhere; LCP checked on home, watch and reels |
| | **Step total** | **13.5** | Re-estimated from 10 days: every route of ten modules, in two directions and two themes |

### Dependencies

All feature steps (1–8) must have their screens in place.

### Acceptance tests

- axe reports no serious or critical violations on any route, in Arabic and English.
- No colour literal outside `tailwind.config.js` and `src/style.css`.
- The main bundle stays within the agreed budget; the lazy chunks are not in `precache.json`.
- Screenshot baselines for key screens pass in both directions and both themes.

### Risks

Late UI churn from earlier steps; screenshot baselines catch regressions.

### Deferred, with reasons

| Item | Reason |
|---|---|
| User-chosen accent colours for pages and shops | The brand system is fixed; low value for now |
| Native app design work | No native apps |

---

## Step 10 — Integration tests

**Goal.** Prove the modules work together under failure and load before public launch. Each milestone already ships its own tests; this step adds the cross-module suites and the release rehearsal.

**Owning services.** All, plus `.github/workflows/ci.yml`, `scripts/smoke_test.py` and `libs/tara_events/tara_events/schemas/`. **New services:** none.

### Milestones

| ID | Milestone | Days | Scope notes |
|---|---|---|---|
| 10.1 | Full CI | 0.5 | Smoke test (`scripts/smoke_test.py`) in CI and a nightly full-stack run. Lint, vitest and Playwright are already in CI from 1.0. |
| 10.2 | Event contracts | 3 | Backfill one JSON Schema per event type and version that existed before step 1 (the schemas folder holds only a README today, per the audit); event types added in steps 1–8 already have one (section 3.2); producer and consumer contract tests in CI |
| 10.3 | Cross-module journeys | 5 | Playwright, Arabic and English: new user → post → group → story; buyer ↔ seller → order → review; creator → reel → analytics; advertiser → top-up → sponsored post served; recruiter → job → application → interview; moderator → report → removal → appeal → reversal |
| 10.4 | Privacy and authorisation matrix | 3 | Viewer (self, friend, follower, stranger, blocked, minor) × audience × surface (detail, lists, search, feed, previews, media URLs) across services; IDOR suite |
| 10.5 | Resilience | 3 | Out-of-order delivery, DLQ replay, broker outage, graph or media down (fail closed), Redis restart, transcoder crash loop |
| 10.6 | Load and capacity | 2.5 | k6 on feed, watch events, ad events and 500 WebSocket sockets; transcode throughput; Redis memory; on the target server |
| 10.7 | Deploy and restore rehearsal | 2 | Fresh deploy and upgrade from today's schema on staging, following the per-step deploy notes; backup and restore including the new volumes; each runbook in [06-documentation-plan.md](06-documentation-plan.md) exercised once; erasure (L.5) run end to end on a test account |
| | **Step total** | **19** | |

### Dependencies

All earlier steps, and launch hardening L.1–L.6.

### Acceptance tests

- CI runs backend suites, lint, vitest, Playwright and contract validation on every PR.
- At least one end-to-end journey per module passes in both locales.
- Every producer's payloads validate against their schemas.
- Capacity numbers are written down for the target server.
- A restore rehearsal from backup brings back a working stack.

### Risks

Flaky end-to-end tests on a full compose stack in CI; keep journeys few and stable, and quarantine flaky tests quickly.

### Deferred, with reasons

| Item | Reason |
|---|---|
| Chaos testing in production | Staging rehearsal first |
| Kubernetes test environments | Kubernetes is frozen |

---

## 16. Total effort and staffing

| Step | Base days | Cuttable inside the step | Base days without cuttable |
|---|---|---|---|
| 1 Shared social core (with 1.0) | 72 | 1.17 (2.5) | 69.5 |
| 2 Profiles + notifications | 54.5 | 2.19 (3.5) | 51 |
| 3 Messenger | 39.5 | — | 39.5 |
| 4 Marketplace | 37 | — | 37 |
| 5 Video + reels | 90 | — | 90 |
| 6 Ads manager | 52 | — | 52 |
| 7 Professional | 31.5 | — | 31.5 |
| 8 Admin dashboard | 44.5 | 8.14 (1.5) | 43 |
| 9 Design system pass | 13.5 | — | 13.5 |
| 10 Integration tests | 19 | — | 19 |
| L Launch hardening | 29 | — | 29 |
| Docs (06: ADR backfill 2, staff guides 3) | 5 | — | 5 |
| **Total** | **487.5** | **7.5** | **480** |

- **What "cuttable" means now:** only 1.17 (crawler previews), 2.19 (email digest) and 8.14 (immediate token revocation) are cuttable. Events (1.13, 1.14), sounds (5.13) and captions (5.14) are explicit module requirements and stay in scope unless the product owner signs off on dropping them (decision 14 in [section 21](#21-decisions-needed-from-the-product-owner)).
- **Contingency: 35–50%.** These are design-time estimates for an engineer who already knows Tara, while the project is in practice one developer on one server running 43 containers (`docs/architecture/project-review-and-plan.md` §6). Planning range: **about 658 to 731 engineer-days**. Use 50% for any external commitment.
- **Where the numbers come from:** the ten module designs added up to about 386 days. Building shared work once (section 4) saved about 35 days; the fixes required by the verify passes added about 30 days; the design system pass and the integration step add about 30 days. The critic review of this roadmap added 75 days: launch hardening (29); the broker migration, caller-specific secrets, Playwright in CI and deploy safety in 1.0 (+6); private media and upload safety in 1.5 (+4); re-estimates of 3.7 (+2.5), 5.2 (+4) and step 9 (+3.5); video and reel ads (6.12, +4.5); file scanning (3.10, +3); previously unscheduled requirements (group suggestions, profile Videos and Reels tabs, order notifications, `mentions_from`, the chat file and video composer, report endpoints: +9); data migrations, compatibility releases, the finance role, age-band targeting, the suspension ordering and the remaining smaller changes, net of work moved out of 3.2, 4.2 and 10.1 (+4.5); and documentation (+5).
- **Staffing:** one engineer takes about 3.2 to 3.5 years with contingency. Two engineers take about 19 to 21 months. A third engineer brings this to about 13 to 14 months, close to the critical-path limit, with more coordination cost.

**New containers** introduced by this plan: `media-transcoder` (1.5 GB), `media-consumer`, `livekit` (512 MB), `ads-consumer`, `admin-worker`, `admin-consumer`, `identity-consumer`, a profile activity consumer and `redis-hot` (from the module designs, together roughly 3.5 GB), plus `media-scanner` (clamd, about 1.2 GB, 3.10), the production observability stack (about 1 GB, L.1) and separate beat containers (up to about 0.5 GB, L.2). In total about 6 GB more memory. Today's stack is 43 containers using 5.7 GB (`docs/architecture/project-review-and-plan.md`, line 38); the memory figures for the new containers come from the module designs and were not measured.

---

## 17. Critical path

The critical path is the longest chain of milestones that must happen in sequence because each needs the one before. Everything else can overlap when more than one engineer is available.

| # | Milestones | Days | Why it is on the chain |
|---|---|---|---|
| 1 | 1.0c + 1.0g DLQ broker migration and deploy safety | 3.5 | Every later event type relies on correct DLQ routing and the two-release rule; the other 1.0 items run in parallel |
| 2 | 1.1 + 1.2 Correctness and moderation hardening | 6.5 | Fixes the behaviour later features build on |
| 3 | 1.5 Media ownership, privacy and upload safety | 6.5 | Every media feature after this uses it |
| 4 | 1.6 Relationship privacy, counters, batch relationships | 5.5 | Visibility for every list surface, profiles, reels and video |
| 5 | 1.7 Feed ranking v1 | 5.5 | Reels ranking builds on its statistics and session design |
| 6 | 2.7 Posting as a Page | 4.5 | Needed by business sellers, ads, professional and page channels |
| 7 | 2.12 Age gate | 2 | Needed by reels, ads, marketplace and professional |
| 8 | 2.14 + 2.16 Notification registry and aggregation | 8 | Every later notification kind plugs into it |
| 9 | 5.1 + 5.2 Prerequisites and shared video pipeline | 15.5 | Everything video-related needs it, including 6.12 |
| 10 | 5.4 + 5.5 Video and reel domains | 9 | Players, telemetry and discovery need them |
| 11 | 5.6 Unified telemetry | 5 | Ranking, analytics and video-ad viewability need it |
| 12 | 5.11 Reels feeds and ranking | 7 | The longest product chain in step 5 |
| 13 | 5.15 Safety, moderation and lifecycle | 5 | Evidence endpoints the admin console needs |
| 14 | 8.1, 8.2, 8.4, 8.5 Audit, evidence, suspensions, propagation | 18.5 | Needs every service's target endpoint and consumer |
| 15 | Step 9 Design system pass (L.5 erasure, 12 days, runs alongside) | 13.5 | Needs all screens; erasure needs settled data models after step 8 |
| 16 | Step 10 Integration tests | 19 | Needs everything, including L.1–L.6 |
| | **Critical path total** | **≈ 134.5** | About 182 to 202 days with contingency |

**Off the critical path** (can run in parallel once their dependencies are met): the rest of 1.0, most of step 1 (stories, groups, events, search v2, previews), profiles extras (2.8–2.11, 2.19), all of step 3 except what marketplace needs (3.1), step 4, step 6 except 6.12 (which waits for 5.2, 5.6 and 5.11), step 7, the rest of step 8, and launch hardening L.1–L.4 and L.6 at the points given in [section 5.3](#53-launch-hardening-track-l).

With two engineers, a practical split is:

- **Track A (critical path):** 1.0c and 1.0g → step 1 → 2 (2.7, 2.12, 2.14, 2.16) → 5 → 8 (8.1, 8.2, 8.4, 8.5) → 9 → 10.
- **Track B:** the rest of 1.0, L.2, the rest of steps 1 and 2, L.1 and L.3 (before the beta) → 3 → 4 → 6 (6.12 last, after 5.11) → 7 → L.4 → the rest of step 8 → L.5 and L.6 (alongside step 9).

Track B still follows the mandated order among its own steps.

---

## 18. The first two weeks

Ten working days for one engineer, plus owner tasks in parallel. Milestone 1.0 is now 8.5 days because it includes the broker migration and Playwright in CI, so the plan covers 1.0 and the start of 1.1.

| Day | Engineer | Product owner |
|---|---|---|
| 1 | **1.0a** Add `npm run lint` and `npm test` to the frontend job in `.github/workflows/ci.yml`. **1.0b** Add `ADS_SERVING_ENABLED` (default off when `TARA_ENV=production`) with a deploy check, and a test that the feed slot is empty when it is off. | Start the staging deploy on a real Dokploy server using `docs/deploy/DOKPLOY.md` and `scripts/gen-dokploy-env.sh`, with real SMTP. Decide what to do with `MARKETPLACE_AUTO_APPROVE` on staging. |
| 2 | **1.0d** Caller-specific secrets on identity's `/internal/v1/`: identity picks the key by caller (admin for now), rejects the shared secret, and `scripts/gen-dokploy-env.sh` generates the new secret for identity and admin only. | Finish the staging deploy and run `scripts/smoke_test.py` against it. Test Web Push on a real browser. |
| 3 | **1.0e** Ads-only serve-token secret with a 30-minute acceptance window for old tokens. **1.0h** `maxmemory 200mb` and `noeviction` on the shared Redis. | Choose MinIO or Cloudflare R2 for storage. |
| 4 | **1.0c** Broker migration, part 1: per-queue `dead-letter-routing-key` policies, the worker binding its DLQ with its own queue name (main-queue arguments unchanged), and the topology script (unbind `#`, drop foreign DLQ copies, rollback). | Decide team size for the next six months ([section 21](#21-decisions-needed-from-the-product-owner)). |
| 5 | **1.0c** Part 2: restore a staging broker backup locally, rehearse the script and the rollback, and add the acceptance test (a failure in service A appears only in A's DLQ). | Review the week-1 PRs. |
| 6 | **1.0c** Part 3: apply on staging and check DLQ depth per service. **1.0g** begins: the alternate-exchange policy on `tara.events` and the `tara.events.unrouted` queue with a replay command. | Start the legal review: minimum age per market, data protection (Egypt PDPL, KSA PDPL, UAE PDPL), prohibited items, moderation of private messages. |
| 7 | **1.0g** Worker and consumer entrypoints wait for `manage.py migrate --check`; the two-release rule and the emission-flag convention written into the deploy runbook. Open the PRs for 1.0a–1.0e, 1.0g and 1.0h. | Decide server size, including memory for `media-scanner` and the observability stack ([section 21](#21-decisions-needed-from-the-product-owner)). |
| 8 | **1.0f** Playwright in CI against the dev compose stack: pick a reduced profile that fits the runner, and run in Arabic and English. | Confirm the launch model (invite-only beta or public, [section 19](#19-launch-gates-recommendation)). |
| 9 | **1.0f** Make the existing `frontend/web/e2e/` specs green in CI, quarantine flaky ones with an owner, and open the PR. | — |
| 10 | **1.1** Feed: the `relabel_feed_reasons` command, run on staging before the new unfollow rule is switched on. | Review the week-2 PRs. |

**Exit criteria at the end of week 2**

- Staging runs on a real Dokploy server and the smoke test passes on it.
- CI runs lint, vitest and Playwright for the frontend.
- All of 1.0 is merged with tests; the DLQ migration has been applied on staging and its rollback rehearsed; all 15 backend suites are green.
- 1.1 is in progress.

**Week 3 continues with** the rest of 1.1, then 1.2 (the appeal-ownership item can then be ticked off in the open list of `docs/architecture/project-review-and-plan.md`), L.2 (dedicated beat) and 1.3.

---

## 19. Launch gates (recommendation)

The build order is fixed, but the product owner decides when real users come in. These gates say what must exist first. They do not change the order of the steps.

**Invite-only beta** (after step 2):

- Staging deploy proven, backups tested.
- 1.0, 1.1 and 1.2 shipped; the ads serving switch off; the marketplace closed or its auto-approve decision made.
- Private content media and EXIF stripping (1.5).
- Age gate (2.12) and cookie-only refresh tokens (2.13).
- Production observability with alerts (L.1), dedicated beat (L.2), and Postgres and Redis sizing (L.3).
- Staff 2FA (L.4) if anyone other than the owner holds a staff role.
- A written content policy, and the owner or a named person able to act on reports.

**Public launch** (additionally):

- Suspensions and their propagation (8.4, 8.5), case evidence (8.2) and appeals that reverse decisions (8.8).
- Account deletion and erasure across services (L.5).
- Two-factor authentication for every staff account (L.4).
- CSAM handling in place for public image and video uploads (L.6).
- File scanning (3.10), or the product owner's written decision to use manual review instead.
- Shared Redis raised to 512m.
- Legal review signed off.
- Step 10 rehearsal passed.

**If a public launch is needed earlier than step 8,** pull 8.1, 8.2, 8.4 and 8.5 (18.5 days) forward to right after step 2, together with L.4–L.6. That is the only change to the order this roadmap recommends considering.

---

## 20. Deferred work, consolidated

| Item | Module | Reason | Revisit when |
|---|---|---|---|
| Real online payments and escrow | Marketplace, Ads | No legal merchant entity, seller KYC, PCI scope, webhooks or refunds | A merchant account and legal setup exist |
| Real age verification (ID documents, face checks) | All | Vendor cost, data minimisation and privacy law. A self-declared age gate (2.12) with minor protections is built instead | A market or regulator requires it |
| Account deletion and erasure across all services | Identity, all | No longer deferred: scheduled as L.5 after step 8, once data models settle | **Before public launch** (L.5) |
| Tax invoices and postpaid ad credit | Ads, Marketplace | Needs finance, legal and an invoicing provider | Business advertisers ask for it |
| Shipping integrations | Marketplace | Carrier contracts, labels and tracking | Orders volume justifies it |
| End-to-end encrypted messaging | Messenger | Conflicts with search, moderation evidence and multi-device history | A key-management design exists |
| Call recording and transcription | Messenger | Consent, storage and an extra heavy container | Clear user demand and consent UX |
| Native mobile push and CallKit | Notifications, Messenger | No native apps | Native apps exist |
| Live streaming | Video | LiveKit ingress/egress, low-latency HLS, real-time moderation | After step 5 is stable |
| Licensed music and Content ID | Reels, Video | Licensing contracts and a vendor | Reels gain traction |
| Automatic captions | Reels, Video | CPU/GPU cost on one server | A GPU worker is available |
| ML classifiers | Admin | Vendor and legal agreements (CSAM hash matching is no longer deferred: L.6) | Before scale |
| Separate secrets for the remaining internal endpoints | All | They are read-only; identity's privileged endpoints and ads serve tokens are covered by 1.0d and 1.0e | A service needs a privileged internal write |
| ML ranking and A/B testing | Social, Reels, Video | No engagement data yet | Heuristics have run for some months |
| Custom audiences, lookalikes, pixels, behavioural interests | Ads | Consent and privacy law | Legal sign-off |
| Political ads | Ads | Verified identity, ad libraries, per-country rules | Never by default |
| Paid job promotion, offer letters, talent search | Professional | Payments and verified recruiter identity | Payments exist |
| Video interviews | Professional | Reuse of the step-3 LiveKit setup, kept out to bound scope | After step 7 |
| Shadow banning | Admin | Opaque to users, conflicts with decision notices | Not planned |
| OpenSearch with an Arabic analyzer | Search | Postgres trigram plus normalisation first | Search quality or volume demands it |
| Fan-out-on-read for large accounts | Feed | Only needed past the fan-out cap | Real accounts hit the cap |
| Kubernetes manifests | Infra | Frozen per `docs/architecture/project-review-and-plan.md` | A real need to scale out |

---

## 21. Decisions needed from the product owner

| # | Decision | Why it matters | Needed by |
|---|---|---|---|
| 1 | Team size (1, 2 or 3 engineers) | Calendar ranges from about 13 to about 42 months with contingency | Week 2 |
| 2 | Server size | The plan adds about 6 GB of containers, including a 2-vCPU transcoder, a 1.2 GB clamd and the observability stack | Week 2 (before L.1 and step 3) |
| 3 | Storage: MinIO (images could not be pulled) or Cloudflare R2 | Affects attachments, video storage and egress cost | Before step 3 |
| 4 | Launch model: invite-only beta after step 2, or wait; pull admin suspensions forward? | Changes what must exist before real users arrive | Week 2 |
| 5 | Minimum age per market (13, 16 or 18) and the age gate wording | Drives reels, ads, marketplace and professional behaviour | Before 2.12 |
| 6 | Legal review scope and owner | Data protection, minors, prohibited items, moderation of private messages, job postings | Start in week 2 |
| 7 | Payments provider and timeline | Real payments stay deferred until this is decided | Before step 6 ends |
| 8 | Moderation staffing | Pre-review of listings, creatives and appeals needs people | Before step 4 |
| 9 | Default push settings for noisy kinds (reactions, follows) | Users who never changed settings get the defaults | Before 2.17 |
| 10 | Logged-out public pages for public posts, videos and listings | Share links currently land on a login wall; SEO versus privacy | Before 1.17 |
| 11 | Keep or delete video originals after transcoding | Re-encode ability versus storage cost | Before 5.2 |
| 12 | File scanning: clamd sidecar (3.10) or manual review plus forced download | Scan-clean is required for CVs, receipts and creatives; clamd costs about 1.2 GB of memory | Before 3.10 |
| 13 | Redis sizing: shared Redis `maxmemory 200mb` now and a 512m container before public launch; `redis-hot` memory for ranking (1.7) and reels telemetry (step 5) | A full Redis refuses writes under `noeviction`; telemetry needs its own budget | Before 1.7 (create), before 5.6 (size) |
| 14 | The cuttable list: only 1.17, 2.19 and 8.14 may be cut; dropping events (1.13, 1.14), sounds (5.13) or captions (5.14) needs explicit sign-off because the module requirements name them | Keeps required scope from being cut quietly to meet a date | Before step 1 ends |
| 15 | Age-band ad targeting behind `ADS_AGE_TARGETING_ENABLED` (6.10) | Personalised ads by age fall under the PDPL laws; the flag stays off without legal sign-off | Before 6.10 |
| 16 | CSAM vendor or reporting process (L.6) | Required before public image and video uploads; vendor cost is not in the estimates | Before public launch |

---

## 22. Sources and verification

**Inputs used to build this roadmap**

- The Tara code audits (five areas) summarised in [02-tara-audit.md](02-tara-audit.md).
- The QTech code audits (seven areas). QTech is a read-only reference; nothing from it was run.
- Ten module designs (Social, Marketplace, Video, Reels, Messenger, Ads, Professional, Profiles, Notifications, Admin & Moderation), each with an independent verify pass. Where a verify pass corrected a design, the corrected version is used here, and the corrections that change scope are listed per step.
- A critic review of this roadmap and of 05 (2026-11-03). Its code claims were re-checked against the files in the table below before being applied. Changes that came from it are marked "critic review" in the Source column or in the verification notes.

**Checked directly while writing this roadmap** (read-only):

| Fact | Where |
|---|---|
| Phases 0–6 are reported as done; the open items are appeal ownership, a restricted MinIO user, cookie-only refresh tokens, a real-server deploy with real SMTP and Web Push, page posting/photos/following, ad targeting and images, offline data cache, and frozen Kubernetes manifests | `docs/architecture/project-review-and-plan.md`, lines 5–27 |
| The frontend CI job runs `npm ci` and `npm run build` only | `.github/workflows/ci.yml`, lines 103–110 |
| The Dokploy env generator sets `MARKETPLACE_AUTO_APPROVE=false` and `ADS_AUTO_APPROVE=false` | `scripts/gen-dokploy-env.sh`, lines 158–159 |
| Each service's DLQ is bound to a shared `<exchange>.dlx` with routing key `#` | `libs/tara_events/tara_events/worker.py`, lines 50–51 |
| Main queues are declared with `x-dead-letter-exchange` only, with no `x-dead-letter-routing-key` | `libs/tara_events/tara_events/worker.py`, lines 68–74 |
| The publisher uses `confirm_publish`, with no `mandatory` flag and no alternate exchange | `libs/tara_events/tara_events/publisher.py` (`_ensure_producer`, `publish`) |
| `verify_internal_token` checks one HS256 secret (`TARA_INTERNAL_JWT_SECRET`) and has no issuer parameter | `libs/tara_common/tara_common/auth.py`, lines 131–142 |
| `INTERNAL_JWT_SECRET` is in the env block shared by every service; only identity's internal views accept `identity-internal`, and admin is its only caller (`iss: admin`) | `docker-compose.dokploy.yml`, line 32; `services/identity/identity/internal_views.py`; `services/admin/adminsvc/identity_client.py` |
| The ads serve-token key is an HMAC of the internal secret | `services/ads/ads/serve_tokens.py` (`_key`) |
| Workers run embedded beat with a `/tmp` schedule; only web containers set `RUN_MIGRATIONS=true` | `docker-compose.dokploy.yml`, lines 290–392 and 405–491 |
| Every service except identity sets `ATOMIC_REQUESTS=True` | `services/*/config/settings.py` |
| Media lets the owner, or anyone when the asset is public, see a file; `bytes` is the declared size; video and audio skip the signature check; `scan_status` is set to `clean` with no scan | `services/media/media_app/services.py`, `validation.py`, `tasks.py` |
| SPA uploads default to `visibility="public"` | `frontend/web/src/services/media.ts` |
| `Permissions-Policy "geolocation=(), camera=(), microphone=(self)"` | `frontend/web/nginx.conf`, line 42 |
| `AccountRole` has admin, moderator, ad_reviewer and analyst only | `services/identity/identity/models.py`, lines 70–74 |
| The growth e2e spec opens `/ads` and builds a campaign without funding; the realtime tests connect with `?token=` | `frontend/web/e2e/growth.spec.ts`; `services/realtime/realtime/tests/test_ws.py` |
| Listing currency defaults to `USD` in the model and `EGP` in the create form | `services/marketplace/marketplace/models.py`, line 65; `frontend/web/src/components/marketplace/CreateListingModal.vue` |
| Today's stack is 43 running containers using 5.7 GB of RAM; §6 calls it costly for one developer on one server | `docs/architecture/project-review-and-plan.md`, lines 38 and 184 |
| Prometheus, Grafana and OTel are configured for dev only | `infra/observability/`, `infra/compose/docker-compose.yml` |
| `docs/ecosystem/` did not exist before this review; `02-tara-audit.md` is its companion | directory listing |

**Not verified**

- Every effort figure is a design-time estimate.
- Behaviour described in the audits comes from reading code, not running it, except the two read-only checks noted in [02-tara-audit.md](02-tara-audit.md).
- That a per-queue `dead-letter-routing-key` policy combines with the existing `x-dead-letter-exchange` queue argument on the deployed RabbitMQ 3.13. 1.0c rehearses this on a restored broker, and its fallback does not depend on it.
- The estimated memory of the new containers (including clamd, about 1.2 GB) is taken from the module designs or is a typical figure, not a measurement.
