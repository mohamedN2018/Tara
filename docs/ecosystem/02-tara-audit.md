# Tara architecture audit

Ecosystem review, part 2 · Branch `feat/web-social-platform` · 2026-11-03

**Audience:** Tara engineers and the product owner (Mohammed).

**What this is:** a description of Tara as it exists in code today: the architecture, what each service contains, which features are present, partial or missing per product module, the rules new work must follow, and the known gaps and bugs.

---

## About this document

### Sources and method

- It is built from five code-reading audits of the Tara tree:
  1. identity, profile, graph, admin and `libs/tara_common`
  2. post, feed, search, moderation
  3. chat, realtime, notification
  4. media, marketplace, ads
  5. frontend (`frontend/web`), BFF, edge, deploy and `libs/tara_events`
- It also uses ten module reviews (Social, Marketplace, Video, Reels, Messenger, Ads, Professional, Profiles, Notifications, Admin & Moderation). Each review had a verify pass that re-read the code. **Where a verify pass refuted or corrected an audit claim, this document uses the corrected version.** The corrections are listed in [Appendix A](#appendix-a-corrections-applied).
- Nothing was executed to write this document. The verify passes ran two read-only checks, both noted where they are used:
  - The profile list `FieldError` was reproduced in the running `tara-profile-1` container (Django 5.2.18).
  - `chat_db` uses the `en_US.utf8` ctype (checked in `tara-postgres-1`).
- Test counts are counts of test functions found in the code. The suites were not re-run for this document. "All 15 suites green" comes from the project brief.
- Paths are relative to the repo root. Line numbers are given only where an audit recorded them.

### Status legend

| Status | Meaning |
|---|---|
| **Present** | Works end to end for the stated scope. Caveats may still be listed. |
| **Partial** | Some of it exists, or it exists with a defect that matters. |
| **Missing** | No model, endpoint or UI for it. |

"Verified" means an audit or verify pass read it in code. "Plausible" means it was reasoned from the code but not confirmed.

---

## 1. Summary

- **The architecture holds together.** There are 14 Django 5.2 / DRF services plus a FastAPI BFF stub, and each Django service has its own Postgres database and role. Cross-service data moves through a transactional outbox on RabbitMQ, or through `/internal/v1/` HTTP endpoints. No shared tables were found. RS256 JWTs carry a `roles` claim that every service verifies locally.
- **The social core is solid:**
  - accounts, sessions and rotating refresh tokens
  - profiles with per-field privacy, and Pages with member roles
  - friends, follows and blocks
  - posts with four audiences, seven reaction types, comments, shares, polls, hashtags, mentions and link previews
  - a fan-out-on-write home feed with one sponsored slot
  - DMs and groups with voice notes, reactions and read receipts
  - a basic marketplace
  - in-app notifications plus Web Push
  - reports, cases and appeals
  - an ads baseline with creative review
- **Whole product modules are missing:** video, reels, stories, groups/communities, events, trending, professional (jobs, CVs, skills), orders and payments, voice and video calls, and email notifications. Media stores video but does not transcode it, and the UI has no `<video>` element.
- **The most serious problems are security and privacy:**
  - One shared internal JWT secret lets any compromised service grant itself admin.
  - Media access is "public to any logged-in user", which exposes DM images and voice notes.
  - Friend and follower lists ignore privacy and blocks.
  - Hashtags from private posts are indexed.
  - Paid ad campaigns go live with no payment check.
  - Anyone can appeal any moderation case.
  - In production there is no way to suspend an account, because Django admin is not routed.
- **Several confirmed bugs return HTTP 500 or dead-letter events:**
  - `GET /api/v1/profile/me/links|education|work/` fails with a `FieldError` (reproduced).
  - A registration display name of 81–120 characters makes profile creation dead-letter, so that account never gets a profile.
  - Non-numeric marketplace price filters return 500.
  - Moderation `assign()` can reopen resolved cases and can raise `IntegrityError`.
  - Negative voice-note durations return 500.
- **Platform gaps:**
  - The dead-letter queue binding copies every service's failures into every DLQ.
  - Celery beat is embedded in each worker, so workers cannot scale past one replica.
  - Production has no observability stack.
  - CI does not run the frontend tests.
  - The event JSON Schemas promised in `libs/tara_events/tara_events/schemas/README.md` do not exist.

---

## 2. Current architecture

### 2.1 Services and data ownership

Each Django service owns one Postgres database with its own role and env prefix (e.g. `IDENTITY_DB_*`). Other accounts and objects are referenced by bare UUID fields (`account_id`, `owner_id`, `media_id`, `seller_id` and so on), never by cross-database foreign keys.

| Service | Database (as named in the audits) | Owns | Public prefixes | Dokploy containers |
|---|---|---|---|---|
| identity | `identity_db` | accounts, roles, devices, sessions, refresh tokens, email verification, password reset, security events | `/.well-known`, `/api/v1/auth`, `/api/v1/me` | web, worker (`-B`) |
| profile | `profile_db` | user profiles, field privacy, links, education, work, Pages, Page members, `BlockedPair` read-model | `/api/v1/users`, `/api/v1/profile`, `/api/v1/pages` | web, worker, consumer |
| graph | `graph_db` | friendships, follows (users and pages), blocks, close friends, `AccountRef` read-model | `/api/v1/friends`, `/api/v1/follows`, `/api/v1/blocks`, `/api/v1/social` | web, worker, consumer |
| media | `media_db` | media assets, variants, upload sessions; the only service that talks to MinIO | `/api/v1/media` | web, worker |
| post | `post_db` | posts, polls, media refs, reactions, comments, shares, hashtags, mentions, saved items, post reports, `BlockedPair` | `/api/v1/posts`, `/api/v1/comments`, `/api/v1/saved` | web, worker, consumer |
| feed | `feed_db` | `FeedItem` snapshots per recipient (derived, rebuildable) | `/api/v1/feed` | web, worker, consumer |
| chat | `chat_db` (role `chat`) | conversations, members, messages, attachments, reactions, pins, `BlockedPair` | `/api/v1/conversations`, `/api/v1/messages` | web, worker, consumer |
| realtime | none (`DATABASES = {}`) | WebSocket gateway; presence keys and channel-layer groups in Redis | `/ws/` | daphne web, `realtime-bridge` |
| marketplace | `market_db` (role `market`) | categories, seller profiles, listings, listing media, saves, reports, `BlockedPair` | `/api/v1/marketplace` | web, worker, consumer |
| notification | `notif_db` (role `notif`) | notifications, preferences, push device tokens, delivery log | `/api/v1/notifications`, `/api/v1/devices` | web, worker, consumer |
| search | own DB (`search_db`) | `SearchDocument` index (Postgres is the source of truth; OpenSearch optional) and `BlockedPair` | `/api/v1/search` | web, consumer (no Celery app) |
| moderation | own DB (name not recorded in the audits) | reports, cases, actions, appeals, content policies (unused), moderation audit log | `/api/v1/moderation` | web, worker, consumer |
| admin | `admin_db` | feature flags, system config (unused), audit log, service-health snapshots | `/api/v1/admin` | web only (no worker, no consumer, no outbox) |
| ads | `ads_db` | advertiser accounts, campaigns, ad sets, creatives, reviews, impression/click events, budget ledger | `/api/v1/ads` | web, worker |
| bff | none (FastAPI) | Phase-1 stub (`healthz`, `readyz`, `whoami`) | `/bff` (dev Traefik only) | not deployed |

Redis uses one DB index per service, 0–13 (for example feed 5, realtime 7, marketplace 8, ads 13). Indexes 14 and 15 are free.

### 2.2 Shared libraries (`libs/`)

**`tara_common`**
- `auth.py`:
  - `JWTAuthentication` verifies RS256 tokens (iss `tara-identity`, aud `tara`; key from `TARA_JWT_PUBLIC_KEY` or `TARA_JWKS_URL`, JWKS cached for 300 s). It builds a `TokenUser` from the claims (`account_id`, `email`, `handle`, `scopes`, `roles`) without touching the database.
  - `verify_internal_token` checks an HS256 token for audience only; it does not check the issuer.
  - Per the Admin verify pass, `JWTAuthentication` does not check the token's `type` claim.
- `permissions.py`: `HasAnyRole`, `IsModerator` (moderator or admin), `IsAdmin`. There is no capability layer.
- `pagination.py`: `CursorPagination` (`cursor` plus `limit` ≤ 100). It takes the queryset's explicit `order_by`, otherwise falls back to `-created_at`. The first ordering field must be non-null, and ties are walked with a capped offset.
- `responses.py` and `exceptions.py`: the `{"data": ...}` envelope, the `{"data": [...], "page": {next_cursor, prev_cursor, has_more}}` list envelope, and `{"error": {code, message, request_id, details}}` errors via `tara_exception_handler`.
- `rate_limits.py` / `throttling.py`: `api_throttling()` gives `tara_read` 600/min and `tara_write` 120/min per account; `NUM_PROXIES` comes from `TARA_NUM_PROXIES`.
- `middleware.py`: `RequestIDMiddleware`. It takes an inbound `X-Request-Id` as-is.
- `checks.py`: production-safety checks `tara.E001`–`E006` and `W001`–`W002`, registered in every service's `AppConfig.ready()` and enforced by `manage.py check --deploy --fail-level ERROR` when `TARA_ENV=production`.
- Health probes: `/healthz/`, `/readyz/`, `/startupz/` (database and cache; not the broker).
- `tara_common` has no test suite of its own. Its checks are tested inside identity (`services/identity/identity/tests/test_production_safety.py`).

**`tara_events`**
- `AbstractOutboxEvent` and `AbstractProcessedEvent`. `record_event()` must run inside the business transaction and raises outside an atomic block.
- `EventEnvelope`: `event_id` (uuid7), type, version, `occurred_at`, producer, `actor_id`, `subject_id`, `correlation_id`, `causation_id`, `partition_key`, payload.
- `KombuPublisher` with publisher confirms. `NullPublisher` is used when `RABBITMQ_URL` is empty.
- `publish_outbox` (beat every 2 s, `select_for_update(skip_locked)`, batch 200, `MAX_ATTEMPTS` 8; a broker outage pauses publishing without counting an attempt) and `purge_events` (hourly, 7-day retention).
- `EventWorker` / `consume_events`: topic exchange `tara.events`, routing key = event type, durable queue `<service>.events`. Retry queues at 5 s, 30 s, 120 s, 600 s and 1800 s, then `<queue>.dlq` on `tara.events.dlx`. `--replay-dlq` replays dead letters.
- `idempotent(ProcessedEvent, event_id, "<service>:<handler name>")` wraps each handler in `transaction.atomic`.
- Exercised by 6 tests in `services/identity/identity/tests/test_tokens_and_events.py`. No suite of its own.

**`tara_resilience`**
- `idempotency.idempotent(IdempotencyRecord, request, handler)`: opt-in via the `Idempotency-Key` header, per account, keyed on a request fingerprint. Used by identity register, post create, listing create and ads events.
- `CircuitBreaker` plus timeout, used around every internal HTTP call.

### 2.3 Event backbone

**How it works:** the write and its outbox row commit in one transaction. Celery beat drains the outbox every 2 s. RabbitMQ routes by event type. Each consumer queue binds only the event types its imported `@on_event` handlers register. Delivery is at-least-once with idempotent consumers. Realtime is the exception: it runs with `processed_model=None`, so clients must tolerate duplicate frames. Retries do not preserve order, because they go through delay queues.

**Event catalog** (verified in code):

| Event | Producer | Consumers today |
|---|---|---|
| `account.registered` | identity | profile (`ensure_profile`), graph (`AccountRef`) |
| `account.verified`, `session.created` | identity | none |
| `profile.updated` | profile | graph (`AccountRef.handle`), search (indexed only if `visibility=public`) |
| `page.created` | profile | search |
| `page.member.changed` | profile | none |
| `friendship.requested`, `friendship.accepted` | graph | notification |
| `friendship.removed` | graph | feed |
| `user.followed` | graph | notification (user targets only) |
| `user.unfollowed` | graph | feed (user targets only) |
| `user.blocked` | graph | profile, post, feed, chat, marketplace, search |
| `user.unblocked` | graph | profile, post, chat, marketplace, search |
| `media.uploaded`, `media.processed`, `media.failed` | media | none |
| `post.created`, `post.updated` | post | feed, search, post itself (link preview, mention notifications) |
| `post.deleted` (also on moderation removal) | post | feed, search |
| `post.reacted` (new reactions only), `post.shared`, `user.mentioned` | post | notification |
| `post.commented`, `comment.replied` | post | notification, post itself (comment mentions) |
| `post.reported` | post | moderation |
| `feed.item.added` (one event with a recipients list) | feed | realtime |
| `message.created` | chat | realtime, notification |
| `message.reacted`, `message.read`, `conversation.member.changed` | chat | realtime |
| `message.reported` | **no producer** | moderation |
| `listing.created`, `listing.updated` | marketplace | none |
| `listing.status.changed` | marketplace | search (title only, while active), notification |
| `listing.reported` | marketplace | moderation |
| `marketplace.contact.requested` | marketplace | chat (opens a marketplace conversation) |
| `notification.created` | notification | realtime |
| `moderation.actioned` | moderation | post (post remove/approve), chat (message remove), marketplace (listing remove/approve) |
| `appeal.created` | moderation | none |
| `ad.review.decided`, `ad.impression.recorded`, `ad.click.recorded` | ads | none |

`docs/architecture/phase-0/04-event-contracts.md` also names `user.presence.changed` and `account.suspended`. Neither is emitted anywhere.

### 2.4 Authentication, RBAC and internal calls

- **User auth:**
  - identity issues RS256 access tokens (default TTL 900 s) with claims `sub`, `email`, `type`, `sid`, `scope`, `roles`, `iss`, `aud`, `iat`, `nbf`, `exp`, `jti`.
  - JWKS publishes a single `kid`, so keys cannot be rotated with an overlap window.
  - Refresh tokens are opaque, stored as sha256 hashes, grouped in families with reuse detection.
  - Web gets an httpOnly SameSite=Strict cookie at `/api/v1/auth`. The SPA nevertheless keeps access and refresh tokens in `localStorage` (`frontend/web/src/lib/tokens.ts`), and `project-review-and-plan.md` lists the refresh-token cookie as still open.
- **RBAC:**
  - Roles (`admin`, `moderator`, `ad_reviewer`, `analyst`) live in identity's `AccountRole` table. `is_superuser` maps to `admin` and `is_staff` to `moderator`.
  - Roles travel in the `roles` claim and are enforced locally with `tara_common.permissions` (ads defines `IsAdReviewer`).
  - Role changes take effect at the next refresh, up to 900 s later. The SPA decodes roles only at login and bootstrap.
  - No endpoint checks for `analyst`.
- **Internal calls:**
  - `/internal/v1/` endpoints (identity, profile, graph, media, chat, ads) use `authentication_classes=[]` plus a manual HS256 check of `INTERNAL_JWT_SECRET`, audience `<target>-internal`, about 30 s expiry.
  - The edge never routes them.
  - Callers wrap them in a circuit breaker and degrade safely. Profile treats a Graph failure as "not friends", post fails closed on visibility, and feed shows organic posts only when Ads is down.
  - `INTERNAL_JWT_SECRET` is in `x-common-env` (`docker-compose.dokploy.yml`, line 32), so every container holds it.

### 2.5 Realtime

- `services/realtime/realtime/consumers.py` defines `TaraConsumer` at `/ws/v1/?token=<access>`, behind `AllowedHostsOriginValidator`.
  - It verifies RS256 on connect and closes with 4401 when the token expires.
  - Each account joins group `user.<id>`.
  - `subscribe` joins `conv.<id>` after a membership check against chat's internal API. The check fails closed, and a socket may hold at most 200 subscriptions.
  - `typing` is relayed to subscribers. `ping` gets `pong`.
- `realtime/bridge.py` maps six bus events to client frames: `chat.message.created` (with a per-recipient muted flag), `chat.message.read`, `chat.message.reacted`, `chat.conversation.changed`, `notification.created` and `feed.item.added`.
- `realtime/presence.py` keeps one cache key `presence.<id>` with a 60 s TTL. Nothing reads it (see §6).
- The fallback that reads the token from `Sec-WebSocket-Protocol` never echoes a subprotocol, so browsers abort that handshake; only `?token=` works. nginx turns off `access_log` for `/ws/`.

### 2.6 Media pipeline

- **Upload:** `POST /api/v1/media/uploads/sign/` returns a presigned PUT URL. The browser PUTs to MinIO through nginx `/tara-media/`, then calls `POST /api/v1/media/uploads/<id>/complete/`, which checks the stored size against `MAX_UPLOAD_BYTES` (200 MB for every kind) and the file's magic bytes.
- **Processing:** `media.process_media` makes a 320 px JPEG thumbnail, for images only. Everything else is marked READY with no variants. `scan_status` is set to `clean` without scanning.
- **Access:** downloads are presigned GETs with a 900 s TTL. `_can_view` allows the owner, or anyone authenticated when the asset is PUBLIC. `sign_upload` falls back to PUBLIC, and `frontend/web/src/services/media.ts` uploads as `public` by default.
- **Frontend:** `mediaService.resolveUrl` returns the original's URL and ignores variants, so avatars and grids load originals, one `GET /media/<id>/` per asset.
- **Not in place:** ffmpeg, transcoding, HLS, posters, a batch lookup endpoint, a delete endpoint, and any consumer. `/internal/v1/media/<id>/` (which returns `owner_id`) has no callers.

### 2.7 Edge routing

Production edge: `frontend/web/nginx.conf`, one nginx container (`web`). It serves the SPA and proxies by path prefix. Upstream names are resolved at request time through resolver `127.0.0.11`. Dokploy's Traefik terminates TLS in front of it.

| Path prefix | Upstream | Notes |
|---|---|---|
| `/ws/` | realtime:8000 | 3600 s timeouts, `access_log off` |
| `/tara-media/` | minio:9000 | passes Host through for the signature; 200 MB body; not rate-limited |
| `/.well-known`, `/api/v1/auth`, `/api/v1/me` | identity | auth zone 2 r/s, burst 20. `/api/v1/me` is a plain prefix, so any new `/api/v1/me...` path goes to identity unless it gets its own location. |
| `/api/v1/users`, `/api/v1/profile`, `/api/v1/pages` | profile | |
| `/api/v1/friends`, `/follows`, `/blocks`, `/social` | graph | |
| `/api/v1/media` | media | |
| `/api/v1/posts`, `/comments`, `/saved` | post | |
| `/api/v1/feed` | feed | |
| `/api/v1/conversations`, `/messages` | chat | |
| `/api/v1/marketplace` | marketplace | |
| `/api/v1/notifications`, `/devices` | notification | |
| `/api/v1/search`, `/moderation`, `/admin`, `/ads` | search, moderation, admin, ads | |
| `/assets/`, `/manifest.webmanifest`, `/` | static | assets cached for 1 year; SPA fallback to `index.html` |

- **Headers and limits:** API zone 30 r/s per IP, burst 60. Server-level headers: CSP `default-src 'self'` (img/media `'self' data: blob:`, connect `'self' ws: wss:`, `frame-ancestors 'none'`), HSTS, X-Frame-Options DENY, nosniff, Referrer-Policy, and Permissions-Policy with `camera=()` and `microphone=(self)`.
- **Proxy headers:** nginx sets only Host, X-Real-IP, X-Forwarded-For and X-Forwarded-Proto. It neither sets nor strips `X-Geo-Region`, which identity reads for `ip_region`. `set_real_ip_from` trusts the Docker ranges 172.16/12 and 10/8 without `real_ip_recursive`.
- **Dev edge** (`infra/compose/docker-compose.yml`): Traefik on 127.0.0.1:8080 with the same prefixes, plus `/bff`. It also exposes identity's `/admin`, `/metrics`, `/api/v1/docs` and `/api/v1/schema`. The Vite dev server proxies `/api`, `/ws` and `/__s3` (MinIO).
- **Kubernetes** (`infra/k8s/overlays/*`): Kustomize overlays for the 14 services. They are frozen, the identity ingress lacks `/api/v1/me`, and there are no manifests for web, BFF or MinIO.

### 2.8 Deployment (Dokploy)

- `docker-compose.dokploy.yml` runs:
  - postgres, redis, rabbitmq and minio
  - the 14 HTTP services
  - 11 outbox-relay workers (`celery -A config worker -B`, beat embedded): identity, profile, graph, media, post, feed, chat, marketplace, notification, moderation, ads
  - consumers (`manage.py consume_events`): profile, graph, post, feed, chat, marketplace, notification, search, moderation, plus `realtime-bridge`
  - `web`
- Gaps in that list: admin has no worker or consumer, search has no Celery app, and identity, media and ads have no consumer. The BFF is not deployed.
- Memory limits are 384m for web services, 256m for workers and 192m for consumers. Redis runs `--appendonly yes` with `mem_limit 256m` and no `maxmemory`, shared by every service and by the channel layer.
- Only `web` joins `dokploy-network`. Migrations run only in web containers (`RUN_MIGRATIONS=true`); workers and consumers skip them.
- Each service gets its own `x-<svc>-env` block. Optional values are passed as `${X:-}`, so an empty string can override `os.getenv` defaults. The `.env` must therefore be generated with `scripts/gen-dokploy-env.sh`.
- Celery default queue is `<service>.tasks`. Tasks run eagerly when `RABBITMQ_URL` is empty.
- Workers use `-s /tmp/celerybeat-schedule`, which is lost on every redeploy.
- `infra/postgres/init/01-create-databases.sh` runs only when the volume is first created, and grants every role `CREATEDB`.

### 2.9 Frontend (`frontend/web`)

- **Stack:** Vue 3 + TypeScript + Pinia + vue-i18n + Tailwind, PWA with Web Push. Arabic RTL is the default (`index.html` ships `lang=ar dir=rtl class=dark`) and English is the second language. `src/i18n/ar.ts` and `src/i18n/en.ts` are both 602 lines, and a parity test keeps them in sync.
- **Brand system:** `tailwind.config.js`, `src/style.css`, `src/components/brand/TaraLogo.vue`, `docs/design/brand.md`.
- **Routes:** 26 in `src/router/index.ts`, covering landing, auth, home, profile, friends and connections, messages, marketplace, pages, ads (campaigns, review), saved, posts, search, notifications, settings and admin. `KeepAlive` wraps only `HomeView` (`max=1`, in `src/App.vue`).
- **HTTP:** every call goes through `src/services/*.ts` on one axios client (`src/lib/api.ts`), which does single-flight refresh locked across tabs with `navigator.locks`.
- **WebSocket:** `src/lib/ws.ts` checks the token is fresh before connecting, sends a heartbeat, reconnects with backoff, refetches on `_reconnected` and replays subscriptions.
- **Service worker** (`public/sw.js`): precaches every build asset listed in `precache.json`, serves an offline shell, shows push in the user's language, and only follows same-origin URLs on click.
- **Not present:** any `<video>` element; routes for video, reels, stories, groups, events, trending, jobs or calls.

### 2.10 Tests and CI

Backend test functions per service, as counted in the code. Some are parametrized, so the number of cases run is higher.

| identity | profile | graph | media | post | feed | chat | realtime | marketplace | notification | search | moderation | admin | ads | bff |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 38 | 22 | 9 | 8 | 60 | 9 | 34 | 7 | 9 | 31 | 7 | 6 | ~9 | 18 | 3 |

- `scripts/test-service.sh <svc>` runs `makemigrations --check --dry-run`, then `pytest --create-db` against the real Postgres of the running stack. `scripts/smoke_test.py` exercises the deployed stack.
- **Frontend:** 88 vitest `test`/`it` declarations in `src/__tests__`. Seven are `it.each` tables, which brings the run count close to the stated 127. Playwright has 51 `test()` declarations in `e2e/` (the brief says 50).
- **CI** (`.github/workflows/ci.yml`): ruff, all 15 service suites, docker builds (including web), and compose / kustomize / promtool validation. The frontend job runs only `npm run build`; vitest, eslint and Playwright are not run.

---

## 3. Per-service inventory

Model, endpoint and event names are as found in code. `INTERNAL` marks `/internal/v1/` endpoints. Every Django service also serves `/healthz/`, `/readyz/`, `/startupz/`, Prometheus metrics, `/api/v1/schema/` and `/api/v1/docs/`, which are not repeated below.

### identity (`services/identity/identity`)

- **Models:**
  - `Account` (AbstractBaseUser + PermissionsMixin; uuid7 pk; email login; status `active|pending|suspended|deactivated|deleted`; language, theme, is_staff, `deleted_at`)
  - `AccountRole` (admin, moderator, ad_reviewer, analyst; unique per account+role)
  - `Device`, `UserSession` (coarse `ip_region`, `revoked_at`)
  - `RefreshToken` (`token_hash`, `family_id`, `rotated_from`, `used_at`, `revoked_at`)
  - `EmailVerification`, `PasswordReset` (hashed tokens)
  - `SecurityEvent` (append-only)
  - `TwoFactorSecret` (scaffold, unused)
  - Outbox, processed-event and idempotency tables
- **Endpoints:**
  - `POST auth/register/`, `login/`, `refresh/`, `logout/`, `verify-email/`, `verify-email/resend/`, `password/forgot/` (always 202), `password/reset/` (revokes all sessions)
  - `GET auth/sessions/`, `DELETE auth/sessions/<id>/`
  - `GET|PATCH me/` (language and theme only)
  - `/.well-known/jwks.json`
  - Django `/admin/`
  - INTERNAL `accounts/lookup/?email=`, `role-holders/` (max 200), `accounts/<uuid>/roles/` (GET/POST/DELETE; `actor_id` comes from the body)
- **Publishes:** `account.registered` (email, email_verified, language, display_name, handle), `session.created`, `account.verified`.
- **Consumes:** nothing. There is no consumer process.
- **Async:**
  - `identity.send_email` lives in `identity/tasks_email.py` (autoretry 30 s to 1800 s, max 8). Autodiscovery does not find it; it is registered only because system checks import the URL configuration.
  - Management commands: `create_admin`, `ensure_jwt_keys`, `seed_dev_data` (DEBUG only; it does not emit `account.registered`).
- **Throttles:** scoped `auth_register` 10/h, `auth_login` 20/min, `auth_password` 5/h, `auth_refresh` 60/min. A per-email lockout applies after 10 failures for 900 s. The service does not merge `api_throttling()`, so `/me/` and `/auth/sessions/` have no read/write throttle.
- **Tests:** 38.

### profile (`services/profile/profiles`)

- **Models:**
  - `UserProfile` (`account_id` unique, `handle` unique lowercase, `display_name` max 80, bio 300, intro unbounded `TextField`, city, country, avatar/cover media ids, visibility `public|friends_only|private|custom`, `completion_pct`, `deleted_at`)
  - `ProfileFieldPrivacy` (7 keys: bio, intro, city, country, links, education, work)
  - `UserLink`, `UserEducation`, `UserWorkExperience` (BigAutoField; no `created_at`)
  - `Page` (owner, handle, name, category, description, avatar/cover, contact JSON, location, status `draft|published|suspended`)
  - `PageMember` (owner, admin, editor, moderator, advertiser, analyst)
  - `BlockedPair`
- **Endpoints:**
  - `GET|PATCH profile/me/`; `GET|PUT profile/me/privacy/`
  - `profile/me/links|education|work/` with POST and DELETE only; the GET lists fail, see §6
  - `POST users/lookup/` (≤ 100 ids)
  - `GET users/id/<uuid>/`, `GET users/<handle>/` (blocked either way → 404)
  - `GET|POST pages/` (`?q=`, `?mine=1`), `GET pages/<handle>/`, `GET|PATCH pages/id/<uuid>/`, members CRUD
  - INTERNAL `POST profiles/by-handle/` (≤ 50, used for mention resolution), `GET profiles/<uuid>/snapshot/`
- **Publishes:** `profile.updated` (handle, display_name, visibility, avatar_media_id, changed), `page.created`, `page.member.changed`.
- **Consumes:** `account.registered`, `user.blocked`, `user.unblocked`.
- **Async:** outbox beat jobs. Commands `consume_events [--replay-dlq]` and `publish_profiles` (re-emits `profile.updated`).
- **Privacy** (`profiles/privacy.py`): combines the local `BlockedPair` table with a synchronous Graph relationship call (circuit-broken, falls back to not-friends). `custom` is treated as private.
- **Tests:** 22.

### graph (`services/graph/graph`)

- **Models:**
  - `AccountRef` (populated, never read)
  - `Friendship` (one row per pair, `low < high` check, pending/accepted)
  - `FollowRelation` (`target_type` user|page)
  - `BlockRelation`
  - `CloseFriendRelation` (no API)
- **Endpoints:**
  - friends list, requests (with `?direction=outgoing`), accept, reject/cancel, unfriend
  - followers, following, follow/unfollow (user or page)
  - blocks list, block, unblock
  - `social/<id>/friends|followers|mutual/`
  - INTERNAL `relationship/?a=&b=`, `fanout/<id>/`
  - Every list is unpaginated.
- **Publishes:** `friendship.requested`, `friendship.accepted`, `friendship.removed`, `user.followed`, `user.unfollowed`, `user.blocked`, `user.unblocked`. `subject_id` is the relation id for `user.followed` and the target id for `user.unfollowed`.
- **Consumes:** `account.registered`, `profile.updated`.
- **Tests:** 9.

### media (`services/media/media_app`)

- **Models:**
  - `MediaAsset` (kind image|video|audio|voice|file; status uploading|processing|ready|failed; visibility; `storage_key`; declared `bytes`; mime; `scan_status`; `deleted_at`)
  - `MediaVariant` (kinds thumb|transcode|waveform|preview; only `thumb` is ever written)
  - `UploadSession` (`expires_at` is ignored)
- **Endpoints:** `POST uploads/sign/`, `POST uploads/<id>/complete/`, `GET <id>/`, `GET <id>/download-url/`, INTERNAL `GET media/<id>/`.
- **Validation** (`media_app/validation.py`): MIME allowlist (no `video/quicktime`, no HEIC). Magic bytes are checked for images and PDF, but `matches_signature` returns True for every video type.
- **Publishes:** `media.uploaded`, `media.processed`, `media.failed`.
- **Consumes:** nothing (`TARA_EVENT_QUEUE='media.events'` is set but there is no consumer).
- **Async:** `media.process_media` (declares `max_retries=3` but never calls `self.retry`; `storage.read()` loads the whole object into memory). The Dockerfile has no ffmpeg.
- **Tests:** 8.

### post (`services/post/posts`)

- **Models:**
  - `Post` (uuid7; `author_type` user|page; type text|image|video|link|share|poll; `body` ≤ 20000; audience public|friends|followers|only_me, `CharField(max_length=12)`; `shared_post_id`; `link_preview`; moderation_status ok|pending|removed; counters; `deleted_at`)
  - `Poll`, `PollOption`, `PollVote`
  - `PostMedia` (media id refs)
  - `PostReaction` (7 types, one per account)
  - `Comment` (parent self-FK)
  - `Share`
  - `Hashtag`, `PostHashtag`, `Mention`
  - `SavedCollection`, `SavedItem` (`item_type` is a free `CharField(16)`)
  - `PostReport`, `BlockedPair`
- **Endpoints:**
  - `GET|POST posts/` (`?author_id=`, `?hashtag=`; audience is filtered after pagination; POST takes an Idempotency-Key)
  - `POST posts/batch/` (≤ 50, live content, counts and viewer state)
  - `GET|PATCH|DELETE posts/<id>/` (PATCH edits the body only)
  - `POST|DELETE posts/<id>/reactions/`
  - `GET|POST posts/<id>/comments/`, `POST comments/<id>/replies/`
  - `POST posts/<id>/share|vote/`, `POST|DELETE posts/<id>/save/`, `GET|POST saved/`
  - `POST posts/<id>/report/` (202)
- **Outbound internal calls:** Graph `relationship` (fails closed) and Profile `by-handle` (raises so the consumer retries).
- **Publishes:** `post.created`, `post.updated`, `post.deleted`, `post.reacted`, `post.commented`, `comment.replied`, `post.shared`, `post.reported`, `user.mentioned`.
- **Consumes:** `user.blocked/unblocked`, `moderation.actioned` (post remove/approve), plus its own `post.created`, `post.updated`, `post.commented` and `comment.replied` for link previews (SSRF-safe fetcher in `posts/linkpreview.py`) and mentions.
- **Tests:** 60.

### feed (`services/feed/feed`)

- **Models:** `FeedItem` (recipient, post, author, `score` always 0.0, reason self|follow, snapshot with excerpt ≤ 280 and media ids, `post_created_at`; unique per recipient+post).
- **Endpoint:** `GET feed/`, ordered by `-post_created_at`. The first page adds `data.sponsored` from Ads.
- **Outbound internal calls:** Graph `fanout` (raises so the event retries) and Ads `feed-slot` (fails quietly).
- **Publishes:** `feed.item.added`.
- **Consumes:** `post.created` (fan-out capped at `FANOUT_MAX_RECIPIENTS=5000`), `post.updated`, `post.deleted`, `user.unfollowed`, `user.blocked`, `friendship.removed`.
- **Tests:** 9.

### chat (`services/chat/chat`)

- **Models:**
  - `Conversation` (dm|group|page|marketplace|support; `dm_key` unique; `listing_id`; `last_message_at`)
  - `ConversationMember` (role, `muted_until`, `last_read_message_id`, `left_at`)
  - `Message` (text|image|video|file|audio|voice|system|share; `reply_to`; `edited_at` and `deleted_at`, never written by users)
  - `MessageAttachment`, `MessageReaction` (6 types), `PinnedMessage`, `BlockedPair`
- **Endpoints:**
  - `GET|POST conversations/` (dm or group), `GET|PATCH conversations/<id>/`
  - members add / role / remove
  - `GET|POST conversations/<id>/messages/`, `POST .../voice-messages/` (1–600000 ms)
  - `POST .../read/`, `.../mute/`, `POST|DELETE .../pin/`
  - `POST|DELETE messages/<id>/reactions/`
  - INTERNAL membership check `conversations/<id>/members/<id>/`
- **Publishes:** `message.created` (recipients, muted, `preview = body[:140]`), `message.reacted`, `message.read`, `conversation.member.changed`. All carry a `recipients` list so realtime needs no database.
- **Consumes:** `marketplace.contact.requested`, `user.blocked/unblocked`, `moderation.actioned` (message remove).
- **Rules:** `MAX_GROUP_MEMBERS=256` is defined; non-members get 404.
- **Tests:** 34.

### realtime (`services/realtime/realtime`)

See §2.5. No database and no Celery. `realtime-bridge` runs `consume_events` without idempotency. **Tests:** 7.

### marketplace (`services/marketplace/marketplace`)

- **Models:**
  - `MarketplaceCategory` (parent FK, slug, single English name)
  - `SellerProfile` (rating fields, never updated or exposed)
  - `Listing` (price `Decimal(19,4)` default 0; currency free `CharField(3)` defaulting to USD; condition new|like_new|good|fair; free-text location; 8 statuses; `save_count`; `deleted_at`)
  - `ListingMedia`, `ListingSave`, `ListingReport`, `BlockedPair`
- **Endpoints:**
  - `GET marketplace/categories/`
  - `GET|POST marketplace/listings/` (q, category slug, condition, location, min/max price)
  - `GET marketplace/my-listings/`, `GET marketplace/saved/`
  - `GET|PATCH listings/<id>/`
  - `POST .../publish/`, `.../transition/` (reserve, reactivate, mark_sold, archive)
  - `POST|DELETE .../save/`, `POST .../report/`, `POST .../contact/`
  - No internal endpoints.
- **Config:** `MARKETPLACE_AUTO_APPROVE` defaults to True in code. `scripts/gen-dokploy-env.sh` sets it to false for production.
- **Publishes:** `listing.created`, `listing.updated`, `listing.status.changed`, `listing.reported`, `marketplace.contact.requested`.
- **Consumes:** `moderation.actioned` (remove, reject, approve), `user.blocked/unblocked`.
- **Commands:** `seed_categories` (8 slugs).
- **Tests:** 9.

### notification (`services/notification/notifications`)

- **Models:**
  - `Notification` (recipient, kind, actor, `subject_ref`, `group_key`, body ≤ 300, `read_at`)
  - `NotificationPreference` (`prefs {kind: {in_app, push}}`, `quiet_hours`)
  - `PushDeviceToken` (web subscription, or native token)
  - `NotificationDeliveryLog`
- **Endpoints:**
  - `GET notifications/` (`?unread=1`), `GET notifications/unread-count/`
  - `POST notifications/read/` (`ids` or `all`)
  - `GET|PATCH notifications/preferences/` (PATCH replaces the whole map)
  - `POST|DELETE devices/push-token/`, `GET devices/push-config/`
- **Publishes:** `notification.created`.
- **Consumes:** 10 events, mapped to kinds:
  - `post.reacted` → post.reaction
  - `post.commented` → post.comment
  - `comment.replied` → comment.reply
  - `user.mentioned` → mention
  - `post.shared` → post.share
  - `friendship.requested` → friend.request
  - `friendship.accepted` → friend.accepted
  - `user.followed` → follow (user targets only)
  - `message.created` → message (skips the sender and muted members)
  - `listing.status.changed` → listing.status
- **Async:** `notifications.deliver_push`, queued on commit; VAPID; endpoint allowlist; max 10 subscriptions per account; prunes 404/410; retries 5xx/429. Inside quiet hours pushes are dropped, not deferred.
- **Tests:** 31.

### search (`services/search/searchsvc`)

- **Models:** `SearchDocument` (`doc_type` is a plain `CharField(16)`; the allowed set lives in `DOC_TYPES` in `views.py`: user, page, post, listing, hashtag) and `BlockedPair`.
- **Endpoints:** `GET search/?q=&type=&limit=` (≤ 50, no cursor, returns a `degraded` flag) and `GET search/autocomplete/` (title prefix, 10 results).
- **Behaviour:** `ILIKE '%q%'` ordered by `-updated_at`, with no trigram index and no Arabic normalization. OpenSearch is optional (`SEARCH_USE_OPENSEARCH`) and falls back to Postgres.
- **Consumes:** `profile.updated`, `page.created`, `post.created/updated/deleted`, `listing.status.changed`, `user.blocked/unblocked`.
- **Publishes:** nothing.
- **Tests:** 7.

### moderation (`services/moderation/moderation`)

- **Models:**
  - `Report` (`target_type` is a free `CharField(20)`; free-text reason)
  - `ModerationCase` (open|in_review|resolved; `severity` always 'normal'; `report_count`; `assigned_to`; partial unique `one_open_case_per_target`)
  - `ModerationAction` (remove, restrict, warn, shadow, dismiss, approve)
  - `Appeal`, `ContentPolicy` (unused), `ModerationAuditLog` (write-only)
- **Endpoints:**
  - `GET moderation/reports/` (IsModerator)
  - `POST moderation/reports/file/` (any authenticated user; target types post, comment, message, listing, page, user; no visibility check)
  - `GET moderation/cases/?state=` (sorted by `-report_count`)
  - `POST cases/<id>/assign/`, `POST cases/<id>/action/`
  - `POST cases/<id>/appeals/` (any authenticated user)
  - `POST appeals/<id>/resolve/`
- **Publishes:** `moderation.actioned` (also on an overturned appeal, always as `approve`), `appeal.created`.
- **Consumes:** `post.reported`, `listing.reported`, `message.reported`.
- **Tests:** 6.

### admin (`services/admin/adminsvc`)

- **Models:** `FeatureFlag` (key, enabled, `rollout_pct`, targeting, description), `SystemConfig` (no API), `AuditLog` (`actor_id`, action, target, metadata), `ServiceHealthSnapshot`. `AccountRole` was removed in `0002_remove_role_registry`.
- **Endpoints:**
  - `GET feature-flags/` and `GET feature-flags/<key>/` (any authenticated user)
  - `PATCH feature-flags/<key>/` (admin; upsert plus audit)
  - `GET|POST|DELETE roles/`, `GET roles/lookup/?email=`, `GET roles/<uuid>/` (admin; proxied to identity via `identity_client.py`)
  - `GET service-health/` (admin; polls 11 `HEALTH_TARGETS` one after another, without ads, realtime or bff)
- **Events:** none. `TARA_EVENT_PUBLISHER="null"` and there is no `config/celery.py`.
- **Tests:** about 9 (role grant/revoke parametrized over 4 roles).

### ads (`services/ads/ads`)

- **Models:**
  - `AdvertiserAccount` (one per user; `billing_status` default 'active', never read)
  - `Campaign` (free-text objective, lifetime budget, spent, status draft|active|paused|completed, schedule)
  - `AdSet` (targeting JSON, "not evaluated yet"; placement feed|marketplace|search; cpc; cpm; frequency cap)
  - `AdCreative` (headline, body, unvalidated `media_id`, cta, https `link_url`, review status)
  - `AdReview`
  - `AdImpressionEvent`, `AdClickEvent` (2-hex `viewer_bucket`)
  - `AdBudgetLedger` (written on every debit, never exposed)
- **Endpoints:**
  - `GET|POST ads/campaigns/` (unpaginated; GET auto-creates the advertiser account)
  - `PATCH ads/campaigns/<id>/` (active|paused), `GET .../report/`
  - `GET|POST .../ad-sets/`, `POST ads/ad-sets/<id>/creatives/`
  - `GET ads/review-queue/`, `POST ads/creatives/<id>/review/` (IsAdReviewer)
  - `POST ads/events/` (serve token, Idempotency-Key, `ad_events` 600/min)
  - INTERNAL `GET ads/feed-slot/` (only caller: `services/feed/feed/ads_client.py`)
- **Serve tokens** (`ads/serve_tokens.py`): HS256 with a key derived from `INTERNAL_JWT_SECRET`, 30-minute TTL, bound to `sub` and `cid`. Each `jti` can be spent once per kind via `cache.add`.
- **Config:** `REST_FRAMEWORK` sets only `ScopedRateThrottle`, without `api_throttling()`.
- **Publishes:** `ad.review.decided` (no owner id), `ad.impression.recorded`, `ad.click.recorded`.
- **Consumes:** nothing.
- **Tests:** 18.

### bff (`services/bff`)

FastAPI. `GET /healthz`, `GET /readyz` (checks identity JWKS), `GET /bff/v1/whoami` (verifies the token locally via PyJWKClient, then calls identity `/me/`). Routed only by dev Traefik; the SPA never calls it.
- `whoami` reads a `scope` claim, while RBAC lives in `roles`.
- `verify_token` maps every exception to 503.

**Tests:** 3.

---

## 4. Feature coverage matrix

These statuses already include the verify-pass corrections. Rows marked **(c)** were changed by a correction; see Appendix A. "Owner" is the service that holds the data.

### 4.1 Platform (identity, infrastructure)

| Feature | Status | Evidence / notes |
|---|---|---|
| Registration + email verification | Present | `identity/services.py`; login blocked until verified. Existing emails get 409, which reveals that an account exists. |
| Login, RS256 + JWKS, roles claim | Present | `identity/tokens.py`; single `kid`, no rotation overlap. |
| Refresh rotation + reuse detection | Present | Family revoke on replay. The SPA still stores tokens in `localStorage`. |
| Sessions list / revoke | Present | `GET/DELETE auth/sessions/`. |
| Password forgot / reset | Present | 1 h token, always 202, revokes all sessions. |
| Brute-force protection | Present | Per-email lockout lets anyone lock out a known email for 15 min. |
| Change password / change email | Missing | `MeView` PATCH allows language and theme only. |
| Two-factor auth | Partial | `TwoFactorSecret` scaffold only. |
| OAuth / social login | Missing | |
| Account deactivation / deletion | Missing | Statuses and `deleted_at` exist but nothing sets them; no `account.deleted` event. |
| Age / date of birth | Missing | No service stores one. |
| Service-to-service auth | Present | Shared HS256 secret with no issuer check (see §6.1). |
| Production-safety checks | Present | `libs/tara_common/tara_common/checks.py`. |
| Event backbone (outbox, retries, DLQ) | Present | `libs/tara_events`; DLQ binding bug (§6.5). |
| Event JSON Schemas | Missing | `schemas/` holds only a README. |
| BFF aggregation | Partial | Stub, not deployed. |
| PWA (shell, install, push) | Present | Offline caches the shell only. |
| i18n ar/en with RTL | Present | Parity test enforced. |
| CI | Partial | Frontend tests not run. |
| Production observability | Missing | Prometheus, Grafana and OTel exist in dev only. |
| Kubernetes manifests | Partial | Frozen; identity ingress missing `/api/v1/me`. |

### 4.2 User profiles (owner: profile)

| Feature | Status | Evidence / notes |
|---|---|---|
| Avatar | Partial | `avatar_media_id` accepts any UUID (no owner, kind or ready check). The SPA loads the original file, never the thumbnail (`frontend/web/src/services/media.ts`, `components/common/UserAvatar.vue`). No crop, no HEIC. |
| Cover | Partial | Same as avatar. No wide variant. |
| Display name **(c)** | Partial | Registration allows 120 characters, `UserProfile.display_name` allows 80. `ensure_profile` raises `DataError` on longer names, the event dead-letters, and that account never gets a profile. An empty display name is accepted on PATCH. |
| Username / handle **(c)** | Partial | Generated at provisioning, read-only afterwards. When registration supplies no handle, the default is the email local-part, which makes it public. No reserved words, so a handle `lookup` is unreachable. |
| Bio / intro | Present | Field privacy works. `intro` has no length limit **(c)**. |
| Location | Present | Free-text city and country. |
| Website | Missing | Only as a generic link. |
| Social links **(c)** | Partial | Create and delete only. `GET profile/me/links/` raises `FieldError` (reproduced). `URLField` also accepts `ftp://`. |
| Friends / followers / following counts and lists | Partial | Lists live in graph, unpaginated, no counts, no `following` endpoint. `lib/useProfile.ts` loads and shows a restricted profile's friend list **(c)**. |
| Posts tab **(c)** | Partial | `GET /posts/?author_id=` paginates first and filters audience afterwards, so pages can be empty with `has_more=true`. The profile lock is not applied on the server. |
| Photos tab | Partial | Built client-side from loaded posts' media; renders originals **(c)**. |
| Videos tab / Reels tab / Listings tab | Missing | Tabs are only posts, photos and friends (`lib/useProfile.ts`). Marketplace has no seller filter. |
| Professional info | Partial | Work and education create/delete; no headline, skills or certifications. |
| Activity history | Missing | `SecurityEvent` is internal only. |
| Privacy settings | Partial | Profile visibility plus 7 field keys. `visibility=custom` is accepted (treated as private). No list-visibility, friend-request or search opt-out settings. |
| Profile types (personal / creator / business) | Partial | Personal is implicit. No creator type. Business = Pages (see 4.3 / 4.11). |
| Profile lifecycle (deletion, takedown) | Missing | `deleted_at` is never set; no moderation enforcement for users or pages. |

### 4.3 Social network (owners: post, feed, graph, search)

| Feature | Status | Evidence / notes |
|---|---|---|
| Home feed | Partial | Fan-out on write, hydrated through `/posts/batch/`, live pill, one sponsored slot. The bugs in §6.2 apply (followers audience, cap, unfollow). |
| Smart ranking | Missing | `FeedItem.score` is always 0.0; feed is chronological. |
| Text posts | Present | Author can still edit a moderator-removed post (§6.1). |
| Image posts **(c)** | Partial | The 4-image cap exists only in `CreatePostCard.vue`. `PostCreateSerializer.media_ids` is unbounded. No lightbox. |
| Video posts **(c)** | Partial | Backend accepts `type=video`, and any bytes labelled `video/mp4` up to 200 MB become READY. No UI, no processing. |
| Link previews | Present | Server-side, SSRF-safe, text only. |
| Reactions | Partial | 7 types. No "who reacted" list, no comment reactions. `unreact()` emits nothing. |
| Nested comments **(c)** | Partial | `CommentList.vue` already shows the "replied to X" label. The real defect: the flat list is cursor-paginated, so a reply whose parent is on another page renders as a root. No edit/delete; `comment_count` never decreases. |
| Shares / reposts | Present | Flattened to the root, audience cannot widen. No dedupe (`Share` has no constraint). |
| Stories | Missing | |
| Friends, follows, requests, blocks | Partial | Lists unpaginated. `block()` emits no `friendship.removed`. Reject/cancel emit nothing. Targets are not validated against `AccountRef`. |
| Close friends | Partial | Model only. |
| Mentions | Present | Resolved via profile, sent only to viewers who can see the post. |
| Hashtags | Partial | Search indexes hashtags of private posts, and never removes hashtag docs **(c)**. |
| Trending topics | Missing | |
| Groups / communities | Missing | |
| Events | Missing | |
| Suggested people / communities | Missing | i18n key `friends.suggestions` is unused. |
| Global search | Partial | Users, pages, public posts, active listings, hashtags. ILIKE, no cursor, no Arabic normalization. The SPA fetches each hit with its own GET. |
| Saved posts **(c)** | Partial | Save works, but `save_item` checks neither existence nor visibility, and collections are unused. |
| Reporting **(c)** | Partial | The backend generic endpoint already accepts post, comment, message, listing, page and user. The UI reports only posts and listings. Moderation dedupes per reporter on an open case. |
| Privacy controls **(c)** | Partial | Audience, field privacy and blocks work. `social/<id>/friends`, `/followers` **and `/mutual`** ignore privacy and blocks. |
| Posting as a Page | Partial | `Post.author_type` exists, but create always makes user posts. |
| Link previews for shared URLs (OG) | Missing | The SPA serves the same shell to crawlers. |

### 4.4 Messenger (owners: chat, realtime, notification)

| Feature | Status | Evidence / notes |
|---|---|---|
| 1:1 chats | Present | `dm_key` dedupe. The create race is not caught, so it can return 500. |
| Group chats **(c)** | Partial | `create_group` never checks `MAX_GROUP_MEMBERS` (257 possible). A re-added member keeps the old `joined_at` and read pointer. New members read the full history. Removed members keep their `conv.<id>` subscription. |
| Realtime WebSocket | Present | See §2.5. |
| Presence | Partial | Write-only; `ping` does not refresh it; one tab closing marks the user offline. |
| Typing indicators | Present | Not throttled, no stop event, relayed even after a block. The echo is dropped client-side. |
| Delivered state | Missing | |
| Read receipts **(c)** | Partial | Works, but the pointer can move backwards, and `member_states` exposes every member's pointer over REST. |
| Text messages | Present | ≤ 8000 characters. |
| Voice notes **(c)** | Partial | Uploaded public. The generic endpoint bypasses the 10-minute cap, and a negative `duration_ms` causes `IntegrityError` (500). |
| Image / video / file attachments | Partial | No ownership or readiness check, unbounded list, public media. No video or file UI. |
| Replies, reactions, mute, message pin | Present | |
| Edit / forward | Missing | `edited_at` is shown in the UI but never written. |
| Delete | Partial | Moderation only; no client event. |
| Conversation search / message search / archive / conversation pin / clear chat | Missing | |
| Unread counters per conversation | Missing | Only the global notification badge. |
| Block | Present | Mirrored `BlockedPair`. Enforced on DM, marketplace and group create/add, not on sends inside groups. |
| Report message | Missing | Moderation consumes `message.reported`, but nothing emits it. |
| Message requests | Missing | Any non-blocked user can open a DM and trigger push. |
| Shared media panel | Missing | |
| Attachment access control | Missing | Owner-or-public only. |
| Message notifications | Partial | One row and one push per message per recipient. Attachment-only messages get an empty preview. Each message is toasted twice in `App.vue`. |
| Voice / video calls (LiveKit/WebRTC) | Missing | Permissions-Policy blocks the camera. |

### 4.5 Marketplace (owner: marketplace)

| Feature | Status | Evidence / notes |
|---|---|---|
| Listings lifecycle | Partial | 8-state machine. No DELETE. Active and removed listings can be edited without re-review. |
| Categories | Partial | Parent FK, but the filter ignores children; single English name; no admin API. |
| Images / videos **(c)** | Partial | `ListingMedia` stored; the detail gallery and card cover render media. `CreateListingModal.vue` always sends `media_ids: []`. No media validation. |
| Search | Partial | DB icontains. The search service indexes the title only, and never on edits. |
| Advanced filters **(c)** | Partial | Backend has condition, location and price, but an empty or non-numeric price returns 500. `MarketplaceView.vue` sends only `q` and category. |
| Location-based discovery | Missing | Free-text location only. |
| Price **(c)** | Partial | Default 0, so free and on-request cannot be told apart. Currency is free text; the backend defaults to USD and the UI to EGP. The modal requires a price. |
| Condition | Present | |
| Seller profiles | Partial | `SellerProfile` is created, never exposed. |
| Seller ratings / buyer reviews / comparisons | Missing | |
| Favorites **(c)** | Partial | `list_saved` shows removed, pending and blocked listings, and reserved/sold ones that then 404 when opened. Save state is never loaded on the detail page. |
| Seller dashboard | Partial | "My listings" only. |
| Buyer dashboard | Missing | |
| Availability | Partial | Reserved, sold and archived states; no quantity. |
| Reporting | Partial | Free-text reason. Reports on listings the reporter cannot see are accepted. |
| Pre-publication moderation **(c)** | Partial | Production sets `MARKETPLACE_AUTO_APPROVE=false`, so publishing goes to `pending_review`. No event reaches moderation, so every production publish stays stuck. The `reject` branch is dead code. |
| Direct seller messaging **(c)** | Partial | The chat thread is created, but neither the UI (no message box, `contact()` sends nothing) nor `ContactView` sends a message. The seller is never notified. A blocked pair dead-letters. |
| Individual vs business sellers | Missing | |
| Checkout / payments / shipping / orders | Missing | |
| Marketplace notifications **(c)** | Partial | Sellers are notified about their own actions, because the handler passes no actor. Moderation also uses the seller as actor, so passing the actor alone would suppress moderation notices. |

### 4.6 Video (YouTube-like)

| Feature | Status | Evidence / notes |
|---|---|---|
| Video upload **(c)** | Partial | Presigned PUT works. Gaps: fallback to PUBLIC; the PUT URL stays reusable after `complete()`; real size is never compared with the declared size; no `.mov`; no signature check. |
| Transcoding (HLS), thumbnails | Missing | No ffmpeg; `_derive_variants` returns `[]` for video. |
| Titles / descriptions / categories | Missing / Partial | Only `Post.body`; no title, lifecycle or categories. |
| Tags | Partial | Hashtags (with the private-post leak). |
| Likes / comments / shares | Present / Partial | Reusable through post endpoints. |
| View counters, watch history, playlists, related, recommended, analytics, creator dashboard | Missing | |
| Creator subscribe **(c)** | Partial | Graph follow works, but neither user nor page targets are validated, lists are unpaginated, and there is no count endpoint. |
| Saved videos **(c)** | Partial | `/posts/<id>/save/` hard-codes `item_type='post'`, while `/saved/` accepts `video`, so the same item can be saved twice under two types. |
| Storage and delivery **(c)** | Partial | Private bucket, presigned GET with Range. Media signs with the MinIO root user; presign TTL is fixed. |
| Playback UI | Missing | No `<video>` in `frontend/web/src`. |
| Feed / search integration **(c)** | Partial | The feed snapshot already stores `type`, so filtering by type is possible (unindexed). Search `doc_type` needs only a `DOC_TYPES` entry, no migration. |
| Moderation of videos **(c)** | Partial | Remove works. Approve emits nothing, so feed and search are not restored. |

### 4.7 Reels (TikTok-like)

| Feature | Status | Evidence / notes |
|---|---|---|
| Vertical feed, snap scroll, autoplay | Missing | No route, component or `<video>`. |
| Upload | Partial | Same as video upload. |
| Sounds / music | Missing | `MediaVariant.Kind.WAVEFORM` exists but is unused. |
| Captions | Partial | Text caption via `Post.body`; no closed captions. |
| Hashtags | Partial | |
| Likes / comments / shares / saves **(c)** | Partial | Reusable, but unsafe as ranking signals: like/unlike/like re-emits `post.reacted`, shares are not deduped, saves are not visibility-checked. |
| Follow creators | Partial | Feed has no follow read-model. |
| Recommendations, creator analytics, efficient delivery, processing notifications | Missing | |
| Reporting **(c)** | Partial | Reports exist. `restrict` and `shadow` are enforced nowhere. |
| Lazy loading | Partial | Only HomeView has infinite scroll. `KeepAlive max=1` would evict HomeView if another view were added. |

### 4.8 Ads Manager (owner: ads)

| Feature | Status | Evidence / notes |
|---|---|---|
| Personal ad account | Partial | Auto-created, named "Advertiser", no endpoint. |
| Business ad account | Missing | One account per user (`owner_account_id` unique). |
| Campaigns with objectives | Partial | Objective is unvalidated and unused. Campaigns cannot be edited. Campaigns go ACTIVE on create. |
| Ad sets **(c)** | Partial | cpm and cpc are both charged when both are set. `AdCampaignView.vue` defaults to cpc 0.10 **and** cpm 1.00, so every ad set made in the UI is charged both ways. |
| Image / video / reels / sponsored-post / marketplace ads | Partial (image) / Missing | `media_id` is not validated or rendered; creatives are text only. Only the feed placement is requested. |
| Targeting (audience, location, age, interests) | Missing | Stored, never evaluated. |
| Daily budget | Missing | |
| Lifetime budget **(c)** | Partial | The final event overspends. Impression cost `cpm/1000` is rounded into `Decimal(19,4)`, so small CPMs are never charged and others are over-charged. |
| Scheduling **(c)** | Partial | Serving honours the schedule; no end > start check; no completion job; the UI does not expose it. |
| Approval workflow | Partial | Creative review works. No reason codes. The decision event is unconsumed and has no owner id. `review_creative` re-decides already-decided creatives. |
| Pause / resume **(c)** | Partial | `set_campaign_status` accepts `active` from any non-completed status, including draft. No ad-set or creative pause. |
| Dashboard: impressions, clicks, CTR **(c)** | Partial | All-time counts. `campaign_report` joins both event tables at once, which multiplies rows. |
| Reach, actual CPC/CPM, conversions, billing history, payment verification | Missing | `billing_status` is never checked. |
| Fraud prevention **(c)** | Partial | Tokens bound to viewer and creative, spent once. The token's `pl` claim is never verified. Tokens are burned before the "is it running" check. Raw viewer ids appear in Redis keys. Clicks are billed without a prior impression. |
| Ad reporting / "why this ad" | Missing | |
| Ads Manager UI **(c)** | Partial | Three views. Vitest covers only the sponsored-slot mapping (`src/__tests__/growth.spec.ts`). |

### 4.9 Professional (LinkedIn-like)

| Feature | Status | Evidence / notes |
|---|---|---|
| Professional profile (headline, open-to-work) | Partial | bio and intro only. |
| Experience / education **(c)** | Partial | Create and delete only. The list GETs fail with `FieldError` (reproduced). |
| Skills, certifications | Missing | |
| CV upload **(c)** | Missing | Media can store a private PDF, but its declared size is never checked against the real object, and `scan_status` is hard-coded to `clean`. |
| Company profiles | Partial | Pages. No company fields or verification. `update_page` emits no event. Page avatar/cover cannot be set through the API. |
| Company followers **(c)** | Partial | Graph stores page follows. No counts. `SocialFollowersView` is user-only. A block does not remove follows of the blocked user's pages. |
| Job listings, saved jobs, alerts, applications, interviews, recruiter dashboards | Missing | `SavedItem.item_type` is a free `CharField(16)`, so a `job` type needs no migration. |
| Professional posts | Partial | Same as posting as a Page. |
| Connections | Partial | Graph friendships, reused. |
| Employment history (linked, verified) | Partial | Free text. |
| Professional notifications, job moderation | Missing | Moderation already accepts `page` reports, but nothing enforces the outcome **(c)**. |

### 4.10 Notifications (owner: notification)

| Feature | Status | Evidence / notes |
|---|---|---|
| Friend request / accepted | Partial | No `subject_ref`, no inline actions. Withdrawn requests stay unread. |
| Reactions **(c)** | Partial | Post reactions only, one row per reactor. Toggling re-notifies. `message.reacted` is not consumed, and it is sent with `type=null` on unreact. |
| Comments, replies, mentions, shares | Present | No comment deep link. |
| Follow **(c)** | Present | Retractions not handled: `user.unfollowed` is not consumed, and block emits no events. |
| Message | Partial | No collapsing, not cleared on read, empty preview for attachment-only messages, duplicate toast. |
| Marketplace | Partial | See 4.5. |
| Order / ads / professional notifications | Missing | |
| In-app list, unread count, mark read | Present | `ReadSerializer.ids` has no cap **(c)**. |
| Click-through deep links | Missing | `NotificationItem.vue` only marks read. |
| Realtime delivery | Partial | Badge counter only; the list is not updated live and reads do not sync across tabs. |
| Grouping, dismiss, retention | Missing | Tables grow without bound. |
| Web Push **(c)** | Partial | Problems: logout does not unregister; `sw.js` drops the query string and hash on click; it shows OS notifications while a window is focused; a retry re-sends to devices that already received the push. |
| Native push (APNs/FCM) **(c)** | Missing | Tokens are stored but never used. Any account that posts a known native token takes it over. |
| Email | Missing | |
| Preferences **(c)** | Partial | PATCH replaces the whole map; kind and channel names are unvalidated. Turning off in-app also blocks push. `SettingsView.vue` repeats the first-dot `replace` bug. |
| Quiet hours | Partial | Pushes are dropped, not deferred. |
| Block hygiene / deleted-content hygiene | Missing | `user.blocked` and `post.deleted` are not consumed. |
| Localization | Partial | Body stored as an English sentence. `kind.replace('.', '_')` replaces only the first dot. |

### 4.11 Administration and moderation (owners: admin, moderation, identity)

| Feature | Status | Evidence / notes |
|---|---|---|
| User management (list, search, detail) | Missing | Only `roles/lookup/?email=`. |
| Account suspensions **(c)** | Missing in production | `Account.Status.SUSPENDED` blocks login and refresh, but it can be set only in identity's Django admin. nginx does not route `/admin/` (only dev Traefik does). No reason, expiry, session revoke or event. |
| Feature restrictions | Missing | `restrict` and `shadow` are not enforced. |
| Page management / suspension **(c)** | Missing | `PageUpdateSerializer` allows draft/published only, and `update_page` refuses changes while suspended. `profiles/admin.py` is dead code because `django.contrib.admin` is not installed. |
| Marketplace moderation **(c)** | Partial | Reported listings are handled. Pre-review intake is missing (see 4.5). `report_listing` has no visibility check. |
| Ad approval **(c)** | Partial | Works, but with no state guard, targeting not evaluated, and no ads consumer. |
| Report intake **(c)** | Partial | The generic endpoint accepts every target type with no visibility or membership check. `report_post` does not exclude deleted posts. A `*.reported` event without a reporter puts `''` into a `UUIDField` and dead-letters. No reason codes, no report throttle. |
| Moderation queue / triage | Partial | Sorted by report count. `severity` is never set. No case detail. The UI shows the raw `target_id` with Dismiss and Remove only. |
| Case evidence (snapshots) | Missing | |
| Enforcement **(c)** | Partial | Post remove/approve, message remove (irreversible), listing remove/approve. Approving a rejected listing is a no-op. Comment, page and user targets are not enforced. |
| Appeals **(c)** | Partial | No owner check, no resolved-state check, duplicates allowed. `resolve_appeal` re-resolves and always emits `approve`. The resolver is recorded only in `ModerationAuditLog`. |
| Decision notices, blocked content, content policies, strikes | Missing | `ContentPolicy` is unused. `Post.ModerationStatus.PENDING` is never set. |
| Audit logs | Partial | Admin `AuditLog` is written after the remote role call (not atomic), and has no read API. `ModerationAuditLog` is write-only. |
| Security / activity logs **(c)** | Partial | `SecurityEvent` is written but unreadable in production. `login_failed` is recorded only for existing accounts. `ip_region` comes from an unstripped header. |
| Platform statistics / analytics | Missing | `analyst` role unused. |
| Service health **(c)** | Partial | Sequential polling. ads, realtime and bff missing. Snapshots never purged. No outbox, consumer or DLQ visibility. The panel is shown to moderators but the endpoint requires admin. |
| RBAC | Partial | Roles only, no capabilities. Stale for up to 900 s. |
| Role management **(c)** | Present | The self-demotion and bridged-role guards exist only in admin. Identity's internal endpoint has no guard and trusts `actor_id`. No outbox event. |
| System settings **(c)** | Missing | `SystemConfig` has no serializer, view, URL or reader. |
| Feature flags **(c)** | Partial | No backend service or SPA feature reads them. Partial PATCH resets omitted fields. Targeting is exposed to any authenticated user. PATCH can create arbitrary keys. |
| Admin console UI | Partial | One `AdminView.vue` behind `meta.staff`. |

---

## 5. Constraints new work must respect

These are the rules the codebase already follows, or that the project plan (`docs/architecture/project-review-and-plan.md` §5) states. New modules should follow them unless a decision record changes them.

### Service and data boundaries

1. **No new services.** New domains go into existing services as separate Django apps, sized so they can be extracted later. Stories and events belong in post; groups and careers in profile; ranking in feed.
2. **Database per service.** Never read another service's tables. Reference other entities by bare UUID, never by cross-database FK.
3. **Cross-service data:** read-models fed by events (as `BlockedPair` and `AccountRef` are today), or `/internal/v1/` reads. Synchronous internal HTTP is for reads only, with an HS256 internal token (aud `<target>-internal`, about 30 s expiry), a circuit breaker, a timeout and an explicit degrade rule: fail closed for visibility and authorization, fail quietly for optional data such as ads.
4. **Media:** only media talks to object storage. Others store `media_id`. Uploads use presign, PUT, then complete. Downloads are presigned GETs (900 s), served same-origin through `/tara-media/`.

### Events

5. Record domain events with `record_event(OutboxEvent, EventEnvelope(...))` **inside the same transaction** as the write (`ATOMIC_REQUESTS=True` in most services; identity uses explicit `transaction.atomic` plus `on_commit`). Never publish inline.
6. Every service that emits needs concrete `OutboxEvent`, `ProcessedEvent` and (if it takes idempotent POSTs) `IdempotencyRecord` tables, `TARA_OUTBOX_MODEL`, and beat entries for `publish_outbox` (2 s) and `purge_events` (hourly).
7. Consumers are `@on_event` handlers in `<app>/handlers.py`, run by `manage.py consume_events` in a `<svc>-consumer` container on queue `<svc>.events`. Handlers must be idempotent.
8. The dedupe key is `<SERVICE_NAME>:<handler function name>`, so renaming a handler resets its idempotency. Handler names must be unique within a service.
9. A handler that must not lose data raises so the event retries. A handler hitting a **permanent** condition must return or no-op, because otherwise it becomes a DLQ poison message (today's chat blocked-marketplace bug).
10. Delivery is at-least-once and unordered on retry. Read-models that can be revoked (blocks, roles, privacy) need ordering guards (`occurred_at`) or tombstones.
11. Payload changes inside an `event_version` are additive. Events that realtime must push carry `recipients[]` so realtime stays database-free. The event contract says no PII beyond ids on broad topics and no raw message bodies (`docs/architecture/phase-0/04-event-contracts.md` §1).

### API contract

12. Single resource: `{"data": ...}`. List: `{"data": [...], "page": {...}}` via `tara_common` `CursorPagination` (`cursor` plus `limit` ≤ 100; first ordering field non-null; never raw offsets). Errors: raise `TaraAPIError` / `Conflict` / `DependencyUnavailable` with stable codes.
13. Non-visible resources return **404, not 403**. Blocked in either direction means the target behaves as if it does not exist.
14. Django core `ValidationError` is not mapped by `tara_exception_handler` and becomes a 500. Validate query parameters with serializers.
15. Throttling: merge `**api_throttling()` into `REST_FRAMEWORK`. A view that sets its own `throttle_classes` replaces the defaults, so include `ReadThrottle` and `WriteThrottle` explicitly.
16. Use an `Idempotency-Key` (`tara_resilience`) for POSTs that are not naturally idempotent. Relationship writes rely on DB unique constraints plus `get_or_create`.
17. Thin views, logic in `<app>/services.py`, `@extend_schema` tags, and OpenAPI at `/api/v1/schema/`.

### Auth and RBAC

18. Only identity issues user tokens. Services verify locally and use `request.user.account_id` and `request.user.roles`. Never call identity per request.
19. Roles live in identity (`AccountRole`). Role changes go through admin, then identity `/internal/v1/accounts/<id>/roles/`. Enforce with `tara_common.permissions`.

### Models, migrations and jobs

20. Primary keys are uuid7 (`tara_events.envelope.uuid7`). Counters use `F()` inside atomic blocks. Money is `Decimal(19,4)` plus `currency CHAR(3)`. Soft delete uses `deleted_at`.
21. Migrations are committed per service, checked by `makemigrations --check`, and applied only by the web container. Large-table indexes need `AddIndexConcurrently` in an `atomic=False` migration.
22. Celery beat runs embedded (`-B`) in each worker, so a worker must stay at **one replica**. The beat schedule file lives in `/tmp` and is lost on redeploy, so daily jobs should be crontab-based and idempotent.
23. Settings are twelve-factor with per-service env prefixes. Dev defaults containing `dev-only` / `change-me` fail `check --deploy`. Generate `.env` with `scripts/gen-dokploy-env.sh`. Never hard-code secrets.

### Edge and frontend

24. Every new top-level `/api/v1/<prefix>` must be added to **both** `frontend/web/nginx.conf` and the Traefik labels in `infra/compose/docker-compose.yml`. Watch the `/api/v1/me` prefix trap. k8s is frozen.
25. The SPA is same-origin: `VITE_API_BASE=/api/v1`, WS URL derived from `window.location`. No hard-coded hosts and no CORS in production.
26. Frontend code: Vue `<script setup lang="ts">`. All HTTP goes through `src/services/*.ts` on the shared axios client (bare `fetch` only for the presigned PUT). Setup-style Pinia stores, lazy routes. Every string needs keys in both `ar.ts` and `en.ts`. Use `dir="auto"` on user content and logical start/end utilities. Use brand Tailwind tokens. No `v-html` on user text.
27. CSP is strict (`default-src 'self'`). Third-party scripts, images and embeds need a CSP change. A location-level `add_header` in nginx drops every server-level header, so re-declare them.

### Privacy

28. Identity stores only the coarse `ip_region`, never the raw IP. Tokens are stored only as sha256 hashes. Ads store only `viewer_bucket`, never raw viewer ids.

---

## 6. Known gaps and bugs

All items below were verified by reading code unless marked *plausible*. Within each group, the most serious come first.

### 6.1 Security and privacy

| # | Issue | Where |
|---|---|---|
| S1 | One HS256 `INTERNAL_JWT_SECRET` is shared by every container, and `verify_internal_token` checks only the audience. Identity's internal role endpoint has no self-demotion guard and trusts `actor_id` from the body, so any compromised service can mint `aud=identity-internal` and grant itself admin. | `docker-compose.dokploy.yml` (x-common-env), `libs/tara_common/tara_common/auth.py`, `services/identity/identity/internal_views.py` |
| S2 | Media access is "owner or any authenticated user if PUBLIC". Uploads default to public (`sign_upload` and `services/media.ts`), including DM images and voice notes, so anyone with a `media_id` can fetch them. `GET /media/<id>/` and `/download-url/` return the **original** file (with EXIF/GPS). | `services/media/media_app/services.py`, `frontend/web/src/services/media.ts`, `MessageComposer.vue`, `MessagesView.vue` |
| S3 | Friend, follower and mutual lists (`/api/v1/social/<id>/friends|followers|mutual/`) are returned to any caller, ignoring profile privacy and blocks. The SPA shows a restricted profile's friends. | `services/graph/graph/views.py`, `frontend/web/src/lib/useProfile.ts` |
| S4 | Search indexes the hashtags of every post, including friends-only and only-me posts, and never removes hashtag documents. | `services/search/searchsvc/handlers.py` (`on_post_created`, `on_post_deleted`) |
| S5 | `edit_post` filters only `deleted_at`, so an author can edit a moderator-removed post; the edit emits `post.updated` and search re-indexes it. | `services/post/posts/services.py` |
| S6 | Appeals: any authenticated user can appeal any case in any state, duplicates are allowed, `resolve_appeal` can re-resolve and always emits `approve`. | `services/moderation/moderation/services.py` |
| S7 | Paid campaigns go ACTIVE on create and `billing_status` is never checked, so ads serve without payment verification. | `services/ads/ads/services.py` |
| S8 | Chat: `MessageCreateSerializer` accepts `type=system` and `share` (spoofed system notices); the attachment list is unbounded; `send_message` does not check media ownership or readiness. | `services/chat/chat/serializers.py`, `services/chat/chat/services.py` |
| S9 | Report endpoints leak existence. `report_post` has no visibility or deleted check; `report_listing` has no visibility check; the generic `/moderation/reports/file/` accepts any target type with no check. | `posts/services.py`, `marketplace/services.py`, `moderation/serializers.py` |
| S10 | Shared-browser push: logout does not unregister the push subscription, and nothing re-binds it on the next login, so the previous user's pushes (including message previews) keep arriving. Native push tokens can be taken over by any account that posts them. | `frontend/web/src/stores/auth.ts`, `services/notification/notifications/services.py` |
| S11 | The SPA stores access and refresh tokens in `localStorage`, and the WS token travels in the query string. The access token carries the raw email claim. | `frontend/web/src/lib/tokens.ts`, `services/identity/identity/tokens.py` |
| S12 | Spoofable headers: nginx neither sets nor strips `X-Geo-Region` (used for `ip_region`); `RequestIDMiddleware` trusts an inbound `X-Request-Id`. | `frontend/web/nginx.conf`, `libs/tara_common/tara_common/middleware.py` |
| S13 | Identity `AccountAdmin` lets any `is_staff` user edit `status`, `is_staff` and `is_superuser`, bypassing every service rule. Dev Traefik exposes identity `/admin`, `/metrics` and docs on localhost. | `services/identity/identity/admin.py`, `infra/compose/docker-compose.yml` |
| S14 | Media uploads: `scan_status` is set to `clean` without scanning; the declared size is stored and never replaced by the real one; the presigned PUT stays reusable after `complete()`; video MIME types skip the signature check. | `services/media/media_app/tasks.py`, `services.py`, `storage.py`, `validation.py` |
| S15 | Media signs URLs with the MinIO root credentials. `project-review-and-plan.md` lists a restricted MinIO user as still open. | `docker-compose.dokploy.yml` |
| S16 | Read pointers: `ConversationSerializer.member_states` returns every member's `last_read_message_id` over REST. | `services/chat/chat/serializers.py` |
| S17 | Identity: register returns 409 for an existing email (enumeration); the per-email lockout lets anyone lock out a known email for 15 min; per the Admin verify pass, `JWTAuthentication` does not check the token `type` claim. | `services/identity/identity/services.py`, `libs/tara_common/tara_common/auth.py` |
| S18 | Ads serve-token weaknesses: the `pl` (placement) claim is never verified; tokens are spent before the "running" check; raw viewer ids appear in Redis keys (`adfreq:{viewer_id}:...`); clicks bill without a prior impression; single-spend depends on Redis `cache.add`. | `services/ads/ads/serve_tokens.py`, `views.py`, `services.py` |
| S19 | No account deletion or erasure path in any service, and no age data anywhere. | identity and all services |
| S20 | `avatar_media_id` and `cover_media_id` (profile) and `media_ids` (post, marketplace, ads creatives) accept any UUID, with no owner, kind or readiness check. | `profiles/serializers.py`, `posts/serializers.py`, `marketplace/services.py`, `ads/models.py` |

### 6.2 Correctness bugs

**Profile and identity**
- `GET /api/v1/profile/me/links/`, `/education/` and `/work/` raise `FieldError` (HTTP 500). The default cursor pagination orders by `-created_at`, which these models do not have. Reproduced read-only in `tara-profile-1`. Untested; the SPA avoids these routes by reading the nested lists from `/profile/me/`.
- Identity allows display names up to 120 characters, profile stores 80. `ensure_profile` raises `DataError`, the event dead-letters, and that account never gets a profile.
- `ProfileUpdateSerializer` accepts `visibility=custom`. `intro`, `Page.description` and `Page.contact` have no length or shape validation.
- `update_page` emits no event, so search keeps stale page names. `PageUpdateSerializer` cannot set page avatar or cover.
- `seed_dev_data` and `createsuperuser` create accounts without `account.registered`, so those accounts have no profile and `/profile/me/` returns 404.
- `identity.send_email` registration depends on system checks importing views (`tasks_email.py` is not autodiscovered). *Fragile, not broken today.*

**Graph**
- `block()` deletes friendships and follows without emitting `friendship.removed` or `user.unfollowed`. Reject/cancel emits nothing.
- `AccountRef` is never read, so requests and follows to nonexistent accounts or pages succeed and notify.
- Page follows skip the self and block checks. `SocialFollowersView` always uses `target_type='user'`. A block keeps follows of the blocked user's pages.

**Post and feed**
- Feed: a `followers` post is sent to followers only, while `visible_to_viewer` also lets friends see it, so friends who do not follow never get it in their feed.
- Feed: recipients are built as a set and cut to 5000 in arbitrary order, so the author can be dropped.
- Feed: `on_user_unfollowed` deletes every item by that author even when the two are still friends.
- Comments are paginated flat, so replies render as roots when their parent is on another page. There is no comment edit/delete, and `comment_count` never decreases.
- `unreact()` and reaction-type changes emit nothing. A react/unreact/react cycle re-emits `post.reacted`. `Share` has no dedupe.
- `SaveView` hard-codes `item_type='post'`, and `save_item` checks neither existence nor visibility.
- Approve after a moderation removal resets the status but emits nothing, so feed and search are not rebuilt.

**Chat and realtime**
- `create_or_get_dm` does not catch `IntegrityError`, so concurrent first DMs return 500.
- `create_group` does not enforce `MAX_GROUP_MEMBERS`.
- Re-adding a member keeps the old `joined_at`, pointer and mute.
- `list_messages` has no join-time filter.
- `mark_read` can move the pointer backwards and emits on every call.
- A negative `duration_ms` on the generic messages endpoint violates `PositiveIntegerField` and returns 500.
- `on_marketplace_contact` raises 403 for blocked pairs inside the consumer, which retries five times and then dead-letters.
- The marketplace conversation gets no first message or event, so the seller is never notified.
- `remove_message` emits no event, cannot be undone, and leaves the preview in existing notifications.
- Realtime: `ping` returns before `presence.refresh()`, so idle users drop offline after 60 s; any one socket closing deletes presence; removed members keep their `conv.<id>` subscription; the `Sec-WebSocket-Protocol` token fallback never echoes a subprotocol.

**Marketplace**
- `?min_price=abc` or an empty `?min_price=` returns 500 (Django `ValidationError`).
- `list_saved` returns removed, rejected, pending and sold listings and blocked sellers, ordered by listing date.
- In production every publish ends in `pending_review` with nothing to review it.
- The `reject` branch of `apply_moderation` can never run.
- `update_listing` edits active and removed listings without re-review.
- `ContactView` ignores the message.
- Frontend: `ListingDetailView.vue` never loads saved state; `CreateListingModal.vue` sends no media and no `Idempotency-Key`.

**Notification**
- `on_listing_status` passes no actor, so sellers are notified about their own actions.
- Attachment-only messages produce empty push and in-app bodies.
- `App.vue` toasts both `chat.message.created` and `notification.created` for each message.
- `push.deliver` raises after looping all tokens, so a retry re-sends to devices that already received the push.
- `sw.js` follows only `target.pathname` on click, dropping `?comment=` and `#hash`.
- Preferences PATCH replaces the whole map.
- `kind.replace('.', '_')` breaks multi-dot kinds (in `NotificationItem.vue` and `SettingsView.vue`).

**Moderation**
- `assign()` on a resolved case reopens it with no audit, and returns 500 (`IntegrityError`) when a newer open case exists for the same target.
- `take_action()` re-actions resolved cases and emits duplicate `moderation.actioned`.
- Concurrent first reports can 500.
- A missing `reporter` in a report event dead-letters.

**Admin**
- `FeatureFlagWriteSerializer` defaults reset omitted fields on PATCH.
- Role audit is written after the remote identity call, so it is not atomic with the change.
- Every service-health request writes one snapshot row per service, never purged.

**Ads**
- The final billable event can push `spent` past the budget.
- The campaign status is checked before the row lock.
- Both cpm and cpc are charged, and the UI sets both by default.
- `cpm/1000` rounds in `Decimal(19,4)`.
- `campaign_report` joins impressions and clicks in one query.
- `GET /ads/campaigns/` creates an advertiser account as a side effect.
- `review_creative` has no state guard.
- `AdCampaignView.vue` loads every campaign to show one.

**Media**
- `process_media` never retries.
- The thumbnail variant is always recorded as 320×320 whatever the real aspect ratio.
- No retry or delete endpoints; abandoned uploads are never cleaned up.

**Frontend**
- The silent refresh does not update `auth.roles`, so role changes need a full reload.
- `CreateMenu.vue` "new post" does not open the composer.
- `localStorage` access is not wrapped in try/catch in `i18n/index.ts`, `stores/ui.ts` and `lib/tokens.ts`.
- `SearchView.vue` fetches each hit separately.
- Only the first feed page carries a sponsored slot.

### 6.3 Missing propagation (events published with no consumer, or never emitted)

- **Published, never consumed:** `account.verified`, `session.created`, `page.member.changed`, `media.uploaded/processed/failed`, `listing.created`, `listing.updated`, `appeal.created`, `ad.review.decided`, `ad.impression.recorded`, `ad.click.recorded`. As a result, advertisers never learn review outcomes, and search never re-indexes listing edits.
- **Consumed, never produced:** `message.reported`.
- **Never emitted although other parts depend on the fact:**
  - account suspension, deletion, role changes
  - `page.updated` / page status
  - comment delete
  - message edit/delete
  - unreact
  - friend-request withdrawal
  - listing review requests
  - moderation decision notices to owners and reporters
- **Not consumed where needed:**
  - notification ignores `message.reacted`, `user.unfollowed`, `user.blocked`, `post.deleted`, `message.read`
  - feed ignores `user.followed` and `friendship.accepted`, so there is no backfill
  - search ignores `page.updated` and listing edits
  - moderation actions `restrict`, `warn` and `shadow`, and targets `comment`, `page` and `user`, are enforced by nobody

### 6.4 Scale and performance

- Every graph list and `/internal/v1/fanout/<id>/` returns unbounded lists. Feed fan-out is capped at 5000 with no fan-out-on-read fallback.
- `visible_to_viewer` makes one synchronous Graph call per distinct non-public author per request. There is no batch relationship endpoint (the plan notes 60 Graph calls per timeline).
- Audience filtering runs after pagination, so pages can be short or empty while `has_more=true`.
- Search: `ILIKE '%q%'` with no trigram index, no cursor and no Arabic normalization.
- Notification: one row and one push per message per recipient (up to 255 per group message). No retention for notifications or the delivery log.
- Ads: `campaign_report` counts raw tables (cartesian join). The plan expects a rollup or OLAP later.
- `media.process_media` reads whole objects into a 256 MB worker with concurrency 2; images share the 200 MB cap.
- Link-preview fetches and Profile/Graph calls run inside consumer transactions, holding DB transactions open during outbound HTTP.
- Admin health polling is sequential (worst case about 11 × 2 s) and writes rows on every request.
- The frontend resolves each media id separately and downloads originals for avatars and grids.

### 6.5 Platform and operations

- **DLQ fan-out bug:** every service binds its `<queue>.dlq` to the shared `tara.events.dlx` with routing key `#`. A dead letter from one service is copied into every DLQ, so DLQ-depth alerts point at the wrong service and `--replay-dlq` re-injects others' failures. `libs/tara_events/tara_events/worker.py`.
- **Beat:** embedded `-B` in every worker, with the schedule file in `/tmp`. Workers cannot scale past one replica, and interval schedules restart on each redeploy.
- **Redis:** one shared instance, `mem_limit 256m`, AOF on, no `maxmemory`, carrying all caches, throttles, presence and the channel layer. An out-of-memory kill drops every service's cache and every WebSocket.
- **Missing consumers / workers:** admin (no outbox, worker or consumer), identity, media and ads (no consumer), search (no Celery app).
- **Production observability:** none. The Prometheus, Grafana and OTel stack exists only in dev. The MinIO healthcheck is `minio --version`, which does not prove liveness.
- **CI:** the frontend job runs only `npm run build`; vitest, eslint and Playwright are not run.
- **Event schemas:** `libs/tara_events/tara_events/schemas/` holds only a README.
- **Env handling:** optional `${X:-}` values become empty strings that override defaults; for example `int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "900"))` would crash on `""`. This matters only when `.env` was not generated by `scripts/gen-dokploy-env.sh` *(plausible)*.
- **Event publisher:** `checks.py` does not require `TARA_EVENT_PUBLISHER=rabbitmq`. With an empty `RABBITMQ_URL`, `NullPublisher` marks outbox rows as published and events are lost *(plausible; low risk on Dokploy, which requires a RabbitMQ password)*.
- **Postgres init:** `infra/postgres/init/01-create-databases.sh` runs only on a fresh volume, so adding a database needs a manual step, and every role gets `CREATEDB`.
- **Deploy env:** the BFF is not deployed; k8s ingress lacks `/api/v1/me`; `replay_dead_letters` declares queues actively, despite its "passive" comment.
- **Housekeeping:** `libs/tara_common/build/lib/tara_common` is a stale, gitignored build copy.

---

## Appendix A: Corrections applied

Each row is a claim from the first-pass audits that a verify pass refuted or corrected. The corrected version is used throughout this document.

| Area | Original claim | Corrected version |
|---|---|---|
| Social – comments | No "replied to" label. | `CommentList.vue` already shows it. The real defect is pagination orphaning replies. |
| Social – reactions | `suppressClick` needs adding to `PostActions.vue`. | Already implemented (long press, hover, suppress click). |
| Social – images | Up to 4 images. | The cap is client-only; the API list is unbounded and copied into every feed snapshot. |
| Social – video posts | Missing. | Partial: the backend path exists and is unsafe (any bytes become READY). |
| Social – reporting | Comments, users and pages cannot be reported; a migration is needed. | The backend generic endpoint already accepts them; target types are free `CharField`s; moderation already dedupes per reporter. |
| Social – privacy | Friend and follower lists leak. | `SocialMutualView` leaks too. |
| Social – saved | Only collection CRUD missing. | `save_item` also checks neither existence nor visibility. |
| Social – hashtags | Private leak and edits not indexed. | Hashtag documents are also never removed. |
| Platform – plan status | Phases 0 and 2 must come first. | The plan doc records phases 0–6 as executed; the media ACL is still not done in code. |
| Marketplace – media | Missing. | Partial: stored, gallery and card render it; only upload and validation are missing. |
| Marketplace – pre-review | Missing. | Partial, and production already runs with pre-review on (`gen-dokploy-env.sh`), so publishes stick. |
| Marketplace – favorites | List unfiltered. | Also, reserved and sold items in the list 404 when opened; the list is unbounded. |
| Marketplace – contact | `ContactView` drops the message. | The UI sends no message either. |
| Marketplace – notifications | Handler passes no actor. | Moderation also uses the seller as actor, so passing the actor alone would hide moderation notices. |
| Marketplace – filters/price | Partial. | Frontend uses `min_price/max_price`; the empty-string 500 is confirmed; the modal requires a price; UI default EGP vs backend USD. |
| Video – upload | Partial. | Also: PUBLIC fallback, reusable PUT URL, declared size never checked. |
| Video – follow | Page targets unvalidated. | User targets are unvalidated too. |
| Video – moderation | Remove and approve work. | Approve emits nothing, so feed and search stay removed. |
| Video – saved | `item_type=video` supported. | Feed-card save uses `post`, so one item can be saved twice. |
| Video – feed type | No type column. | The snapshot already stores `type`; `reason` is self or follow only. |
| Video – regions | The edge supplies `X-Geo-Region`. | No Tara edge sets it; nginx forwards client values. |
| Video – search | Migration needed for `video`. | `doc_type` has no choices; add to `DOC_TYPES` only. |
| Reels – likes and shares | Reusable. | Not safe as signals: unreact emits nothing, toggles re-emit, shares are not deduped. |
| Reels – Redis | AOF needs enabling. | AOF is already on; the real limit is 256m with no `maxmemory`. |
| Reels – media consumer | Add `TARA_EVENT_QUEUE`. | It exists; the consumer command and handlers do not. |
| Reels – originals | Fixed by a batch endpoint. | Three existing endpoints already serve originals of PUBLIC assets. |
| Reels – KeepAlive | ReelsView can be kept alive. | `max=1` would evict HomeView. |
| Messenger – groups | Present. | Partial: no member cap check, stale re-add state, history leak. |
| Messenger – voice | Present. | Partial: negative duration causes a 500. |
| Messenger – receipts | Pointer issues. | Pointers are also exposed to all members over REST. |
| Messenger – block | Enforced everywhere relevant. | Not on group sends; typing still relayed. |
| Messenger – typing echo | Visible echo bug. | Echo is filtered client-side; the server-side waste remains. |
| Ads – pause | Present. | Partial: no state machine; draft can be activated. |
| Ads – serve tokens | Add a placement claim. | `pl` already exists but is never verified. |
| Ads – budget test | Test codifies 120 against 100. | The test asserting `spent == 1.002` (double charge) is the one that breaks. |
| Ads – double charge | Possible. | It is the UI default. |
| Ads – report | Will not scale. | Worse: a cartesian join. |
| Ads – roles | Add `Account.Role`. | Roles are on `AccountRole.Role`. |
| Professional – list GET | Likely 500. | Confirmed by a read-only run in the container; `links` fails too. |
| Professional – `/tara-media/` | No hardening headers. | It inherits the server-level headers; adding any `add_header` there would drop them. |
| Professional – `profile.updated` | Carries handle and display name only. | Carries handle, display_name, visibility, avatar_media_id, changed. |
| Professional – page reports | Missing. | Intake exists for `page`; enforcement does not. |
| Profiles – display name | Present. | Partial: the 120 vs 80 mismatch dead-letters profile creation. |
| Profiles – handle | Immutable, no reserved list. | Also defaults to the email local-part and accepts reserved words at registration. |
| Profiles – avatar | 320×320 thumbnail. | The SPA never uses the thumbnail; it loads originals. |
| Profiles – posts tab | Present. | Partial: filtering after pagination; no server-side profile lock. |
| Profiles – friends | API leak. | The SPA also displays the leaked list. |
| Notifications – native push | Partial. | Missing, and tokens can be taken over. |
| Notifications – web push | Partial. | Also: click drops query/hash; retries re-send; `remote:false` logout cannot reach the server. |
| Notifications – read API | Present. | `ids` is uncapped. |
| Admin – suspensions | Settable in Django admin. | Django admin is not routed in production; effectively missing. |
| Admin – security logs | Visible in Django admin. | Unreadable in production; `login_failed` only for existing accounts. |
| Admin – appeals | No resolver recorded. | Recorded in `ModerationAuditLog`; the real defects are the missing state guard and always emitting `approve`. |
| Admin – feature flags | Partial. | No runtime consumer anywhere. |
| Admin – system settings | Partial. | Missing: nothing reads or writes `SystemConfig`. |
| Admin – pages | Serializer excludes status. | It allows draft and published; `profiles/admin.py` is dead because `contrib.admin` is not installed. |
| Admin – ad approval | Present. | Partial: no state guard, no consumer, targeting not evaluated. |
| Admin – role management | Guards in place. | Guards exist only in admin; identity's internal endpoint has none. |
| Admin – health | ads and realtime missing. | bff also missing; no pipeline (outbox/DLQ) visibility. |

## Appendix B: What this audit did not verify

- No test suite, smoke test or load test was run for this document.
- Runtime behaviour of the Dokploy deployment (Traefik timeouts for large uploads, TLS, the Cloudflare chain) was not checked. The Traefik v3 60 s read timeout concern raised in the Reels review is unverified.
- Whether `pg_trgm` can extract Arabic trigrams was not tested. Only the `en_US.utf8` ctype of `chat_db` was checked.
- Statements quoted from `docs/architecture/project-review-and-plan.md` (container count, open items, phase status) are taken from the module reviews and were not re-read here.
- Database names for moderation and some other services were not recorded by the audits and are not asserted beyond what is written in §2.1.
