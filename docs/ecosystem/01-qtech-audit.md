# QTech architecture audit

> **What this is.** An audit of the QTech Solutions codebase (`Qtech_company`), written for Tara engineers and the product owner. It records what QTech contains, how mature and tested each part is, what is insecure, and which pieces are worth reusing in Tara.
>
> **Source and method**
> - QTech root: `E:\1_AdvancedPro\1-Web_Developer\1-Full_Stack Developer\1_Django\7-QTech-Solution\Qtech_company`. The audit treated it as read-only and changed nothing. All QTech paths below are relative to that root.
> - Eight area audits read the source code: accounts/access, chat/realtime/notifications, social, cms, core/billing/theming, hr/tasks, frontend, and infra/quality. **Nothing was executed**: not the app and not QTech's tests. Maturity labels describe what the code shows, not what was observed running.
> - A second pass, done while designing Tara's ten modules, re-opened the files behind every "reuse for Tara" claim and gave each claim a verdict: **Confirmed** or **Overstated**. Where that pass corrected an audit claim, this document uses the corrected version. Section 9 lists the main corrections.
> - Statements about Tara refer to branch `feat/web-social-platform`.
> - No secret values are reproduced. Where QTech commits secret defaults, only the variable name is given.
>
> Date: 2026-11-03

## Contents

1. [Summary](#1-summary)
2. [Architecture overview](#2-architecture-overview)
3. [Apps in detail: models, features, maturity, tests](#3-apps-in-detail)
4. [Tech patterns](#4-tech-patterns)
5. [Security observations](#5-security-observations)
6. [Tests and quality](#6-tests-and-quality)
7. [QTech compared with Tara](#7-qtech-compared-with-tara)
8. [Reusable for Tara](#8-reusable-for-tara)
9. [Corrections from the verification pass](#9-corrections-from-the-verification-pass)
10. [Appendix: third-party dependencies](#appendix-third-party-dependencies)

---

## 1. Summary

- **Shape.** QTech is one Django 4.2 monolith: 11 apps, one Postgres database, 106 migrations. It has a Vue 3 single-page app in plain JavaScript plus a second mobile PWA entry at `/m/`. Daphne serves HTTP and WebSockets from one process, Celery with beat runs background jobs, and an optional LiveKit SFU provides voice and video calls.
- **QTech already contains a "Tara".** The internal social network and messenger are labelled "تارا / Tara" in the code (`frontend/src/config/nav.js`, plus comments in `backend/core/permissions.py` and `backend/accounts/signals.py`). QTech's social, chat and presence code is effectively a monolith prototype of features Tara is building as services.
- **Quality is uneven.** The code is well commented and most features are wired end to end. But there are only 70 backend tests, all in `cms`, `hr` and `tasks`. There are no frontend tests and no CI, and several authorization bugs are serious (section 5).
- **Worth taking for Tara** (section 8): the LiveKit deployment and call-engine design, ref-counted multi-tab presence, the photo theater and media grid, crawler link previews, the recruitment (ATS) data model, marketplace price semantics, the visibility clock behind watch-time and ad-viewability beacons, GeoIP country lookup, the layered staff-permission algorithm, the push-subscription lifecycle, and a set of small utilities. Nearly all of them need fixes before porting.
- **Must not be copied:**
  - HS256 tokens signed with `SECRET_KEY`
  - tokens in `localStorage` and in WebSocket query strings
  - client-chosen LiveKit room names
  - an unauthenticated call-signaling relay
  - presence broadcast to every connected user
  - private files served from public `/media/`
  - committed secret defaults
  - the authorization bugs listed in section 5

---

## 2. Architecture overview

### 2.1 Stack at a glance

| Layer | QTech |
|---|---|
| Backend | Django 4.2.30, Django REST Framework 3.17.1, djangorestframework-simplejwt 5.5.1 (HS256, rotation + blacklist), django-filter 25.1, drf-yasg |
| ASGI / realtime | Daphne 4.2.1 runs HTTP and WebSocket in one process. Channels 4.3.2, channels-redis 4.3.0 (capacity 1000, expiry 30, raised for ICE bursts), InMemory fallback |
| Background work | Celery 5.6.2 with django-celery-beat 2.9.0 (DatabaseScheduler), Redis as broker and result backend, one default queue, 11 beat jobs |
| Data | Postgres 17 (SQLite when `LOCAL` is true, which is the default), Redis 7 (cache, presence, throttles, channel layer) |
| Media | Local `MEDIA_ROOT` volume served directly by nginx; WebP renditions built on demand. django-storages is installed but no S3 backend is configured |
| Auth | SimpleJWT HS256 signed with `SECRET_KEY`: 60 min access, 14 day refresh, rotation + blacklist. The SPA stores both tokens in `localStorage`. WebSocket auth uses `?token=` |
| Frontend | Vue 3.5 in plain JavaScript (281 files, no TypeScript), Pinia, vue-router, vue-i18n 10, Tailwind 3.4, Vite 6. Two entries: desktop/hub/portal and a `/m/` PWA |
| Calls | LiveKit server v1.8 as a separate Dokploy app plus livekit-client ^2.7.0; P2P mesh fallback |
| Edge | nginx 1.27 gateway with baked config, behind Dokploy's Traefik; Cloudflare in front |
| Deployment | Three compose files (local, dev overlay, Dokploy production) |
| CI | None |

### 2.2 Backend apps

| App | Purpose | Models | Migrations | Own tests |
|---|---|---|---|---|
| `accounts` | Custom email-login user, registration, Google sign-in, email/phone verification, password reset, account lifecycle | 2 (`User`, `AuthSettings`) | 13 | None (indirect through `hr/tests.py`) |
| `access` | Module-level RBAC matrix plus admin read surfaces (audit, overview, monitor, GeoIP) | 2 (`RolePermission`, `UserPermissionOverride`) | 2 | None (indirect through `cms/tests_pages.py`, `hr/tests.py`) |
| `core` | Shared infrastructure: base models, soft delete, audit, presence, push, analytics, GeoIP, renditions, sanitizer, cache, throttles, CSP collector, chatbot engine | 9 | 6 | None (AuditLog checked indirectly) |
| `chat` | Internal messenger: DMs, groups, department/announcement channels, support inbox, calls | 8 | 5 | None |
| `notifications` | Unified in-app notifications with category muting | 2 | 2 | None |
| `social` | Facebook-style staff network ("Tara" in code): posts, comments, reactions, follows, events | 10 | 9 | None |
| `cms` | Company-website CMS: block page builder, media library, blog, portfolio, store, SEO, contact, chatbot | 28 | 42 | `tests_pages.py` (48 tests) |
| `billing` | Client projects, deliverables, invoices (no payment gateway) | 4 | 1 | None |
| `theming` | Admin theme singleton plus per-user colour overrides | 2 | 11 | None |
| `hr` | Full HR/ATS domain (org, attendance, leave, approvals, recruitment, payroll, performance, training) | 48 | 14 | `tests.py` (10 tests) |
| `tasks` | Task management with visibility engine, workflow gates, recurring tasks | 17 | 1 | `tests.py` (12 tests) |

Settings, URLs, ASGI and Celery live in `backend/qtech_config/`.

**Coupling.** The apps are tightly coupled, as is typical of a monolith:
- Foreign keys point across apps everywhere. `hr` and `tasks` reference each other in a circle: `HRProfile.team` points to `tasks.Team`, and `Task.department` points to `hr.Department`.
- Views import other apps' models lazily inside functions.
- A `post_save` signal in `accounts/signals.py` writes HR and Social profiles directly.
- `chat` depends on `hr.Department` and on access-module keys such as `clients.inbox`.
- Nothing goes through an outbox. Side effects (realtime pushes, notifications, emails) run synchronously inside the request, wrapped in `try/except` so they never fail it.

### 2.3 Realtime

| Piece | Where | Behaviour |
|---|---|---|
| Per-user socket | `WS /ws/?token=` → `backend/core/consumers.py` `UserConsumer` | Joins `user_<id>` and one global `feed` group. Handles presence, ping/pong, notification and sidebar fan-out, and relays `call.*` signaling to a target user, with Web Push when the target is offline. |
| Per-conversation socket | `WS /ws/chat/conversations/<id>/?token=` → `backend/chat/consumers.py` `ChatConsumer` | `can_access` gate (close codes 4001/4403/4404). Typing, stop-typing, read, ping. Receives `message.*`, `support.*` and per-room online/offline events. Membership is never re-checked after connect. |
| Server push | `backend/core/realtime.py` `push_to_user` / `push_to_users` / `push_to_group` | Synchronous `async_to_sync(group_send)` inside REST views, using a `{type:'broadcast', event, payload}` envelope. `_jsonable()` coerces UUID, datetime and Decimal values for msgpack. No `on_commit`: a rolled-back write can still emit. |
| Presence | `backend/core/realtime.py` | Redis sorted set `presence:z` scored by heartbeat time (70 s TTL, stale entries evicted on read and write), plus `HINCRBY presence:conn` counting sockets per user. The user goes offline only when the last socket closes, and `last_seen` is stored then. A cache-dict fallback covers dev. The client (`frontend/src/services/ws.js`) pings every 25 s, and `frontend/src/composables/usePresence.js` seeds from REST, applies deltas and re-seeds every 30 s. Transitions are broadcast to the global `feed` group, which every socket joins. |
| Socket auth | `backend/core/ws_auth.py` inside `AllowedHostsOriginValidator` (`backend/qtech_config/asgi.py`) | Validates `?token=` with SimpleJWT `AccessToken`. It does not check `is_active` and never closes sockets when the token expires. Because production `ALLOWED_HOSTS` defaults to `*`, the origin validator does nothing. |

### 2.4 Calls: LiveKit SFU and P2P mesh

Calls are the largest area where QTech has something Tara lacks entirely. Overall maturity: **partial**. There are no tests.

| Piece | Where | What it does | Issues |
|---|---|---|---|
| SFU server | `infra/livekit/docker-compose.yml`, `infra/livekit/livekit.yaml`, `infra/livekit/README.md` | `livekit/livekit-server:v1.8` runs as its own Dokploy app. Config is inline in compose `configs.content`, with the API key and secret interpolated from env, so no secret is in git. Media uses one UDP port (50000, muxed) plus a TCP fallback on 7881, with `use_external_ip`. Signaling on 7880 goes through Traefik over `dokploy-network` as wss. The README is a full runbook (generate keys, DNS record, Cloudflare proxy for signaling only, firewall ports, devtools check). In the local `docker-compose.yml` LiveKit runs inline on 127.0.0.1 with UDP 50000-50019; the dev overlay puts it behind a `calls` profile. | No `turn:` section and no TURN server anywhere, so users behind strict NAT or firewalls will fail. No webhook to the backend and no room limits. |
| Token endpoint | `backend/chat/views.py` `ConversationViewSet.call_token` | `POST /api/v1/chat/conversations/<id>/call-token/` returns `{url, token}`. The token is a hand-rolled PyJWT HS256 token (`iss`=API key, `sub`=user id, video grant roomJoin/canPublish/canSubscribe/canPublishData, 6 h lifetime). Returns 503 when the `LIVEKIT_*` env vars are unset, so the frontend falls back to mesh. Requires `can_post`; client accounts are refused. | The room name comes from `request.data`, so any member of any conversation can mint a token for any room. Client room names (`lk_<convId>_<digits>`) are low-entropy and are exposed in `active-call` and invite payloads. |
| Call state | same file: `call_start`, `active_call`, `call_end`, `call_log` | The active call is held in the Django cache (`call:active:<conv>`, 4 h) so people can rejoin. The outcome is written as a SYSTEM message with hard-coded Arabic text. | Status and duration in the call log come from the client. Any member can end the active call. |
| Signaling | `backend/core/consumers.py` `UserConsumer.receive` | Relays any `call.*` frame that has a `to` field to `user_<to>`, stamping `from`, `from_name` and `from_avatar`. Sends Web Push to offline callees. | No shared-conversation or block check. An unvalidated `int(to)` crashes the consumer. Synchronous Redis and web push calls run inside an async consumer. |
| Engine choice | `frontend/src/composables/useCall.js` | Chooses LiveKit if `VITE_LIVEKIT_URL` was set at build time, otherwise mesh. Both engines expose the same API. | The switch is fixed at build time. |
| SFU client | `frontend/src/composables/useLiveKitCall.js` | livekit-client `Room` with adaptiveStream/dynacast, active speakers, reconnecting state, screen share, raise hand, 35 s no-answer timeout, Web Audio ringtone. | Imported statically (not lazily), numeric identities, client-generated room names, and a `call.end` handler that tears down the current call without checking which room it is for. |
| Mesh client | `frontend/src/composables/useMeshCall.js` | Full-mesh 1:1 and group WebRTC with glare rollback, ICE restart from one side only, Google STUN, and optional TURN from `VITE_TURN_*`. | Static TURN credentials are compiled into the public bundle. It requests notification permission when the module loads. |
| UI | `frontend/src/components/chat/CallOverlay.vue`, `CallPicker.vue` | Adaptive grid, spotlight with filmstrip during screen share, speaking ring, raised-hand badge, reconnecting overlay. Video elements are muted and audio plays through hidden `<audio>` sinks, which prevents echo and allows muting one peer. | No `role=dialog` and no focus trap. `CallPicker` searches the global staff directory. |
| Ringing | `backend/core/push.py`, `frontend/public/sw.js` | VAPID push with `requireInteraction`, `renotify`, the single tag `qtech-call` and a long vibration pattern. | VAPID keys have committed defaults (section 5). |

### 2.5 Frontend

- **Code base.** 281 files under `frontend/src`, none of them TypeScript. Vue 3 `<script setup>` in JavaScript, Pinia option-style stores, vue-router, vue-i18n in composition mode, Tailwind 3, lucide icons, Vite 6.
- **Two Vite entries from one project** (`vite.config.js`):
  - `index.html`: marketing site, staff hub at `/hub` and client portal at `/client`.
  - `m/index.html`: an installable phone PWA under `/m/`, with `DeviceGate` (QR code on desktop) and `InstallGate` (refuses to run in a browser tab).
  Both share `services/api.js`, `stores/auth.js`, `stores/theme.js` and i18n.
- **Service workers.**
  - `public/sw.js`: site Web Push, with RTL and Arabic hard-coded.
  - `public/app-sw.js`: the PWA worker. Cache-first for the shell, network-first for API calls, and no automatic `skipWaiting` (users are prompted to update).
- **HTTP and sockets.**
  - One axios instance (`services/api.js`) adds the Bearer token and `?lang=`, refreshes once and shares that refresh across concurrent requests, and dispatches an `auth:expired` event.
  - Tokens are stored as `qt_access` and `qt_refresh` in `localStorage`.
  - `services/ws.js` is a reconnecting socket: backoff capped at 15 s, an outgoing queue, a 25 s ping, and a wildcard event bus.
- **i18n and RTL.**
  - `ar.json` and `en.json` have 2,920 keys each across 104 namespaces, in full parity.
  - Logical start/end utilities dominate: 235 uses against 2 physical left/right.
  - But 86 files contain hard-coded Arabic, 27 places hard-code `ar-EG`, and none of the 43 mobile `.vue` files use vue-i18n.
- **Defects visible in the code.**
  - Logout does not close the global socket or reset the singleton stores, so the previous user's toasts and call invites can keep arriving in that tab.
  - `app-sw.js` caches authenticated API GETs keyed only by URL and never clears them on logout.
  - TURN credentials are in the bundle.
  - Visitor tracking excludes `/app` and `/admin`, but the hub is at `/hub` and the portal at `/client`, so signed-in pages are tracked.
  - Chart labels use `name_ar` whatever the locale.
  - No Content-Security-Policy is set in `frontend/nginx.conf` or in a meta tag.
- **Tests.** None. Playwright appears only in an untracked screenshot script, `frontend/_shot.mjs`.

### 2.6 Deployment, edge and operations

- **Compose layering.**
  - `docker-compose.yml`: local and self-hosted. Only the gateway is published, on `127.0.0.1:8900`. LiveKit runs inline. pgAdmin sits behind a `tools` profile with weak fallback defaults, bound to localhost.
  - `docker-compose.dev.yml`: a git-ignored overlay driven by `dev.sh` (`-p qtech-dev`, `.env.dev`, ports shifted by 10). LiveKit sits behind a `calls` profile.
  - `docker-compose.prod.yml`: Dokploy with Traefik. A baked-config nginx gateway (`qtech_web`) joins the external `dokploy-network`. A fixed compose subnet (`10.219.7.0/24`) works around Docker address-pool exhaustion. Services use unique aliases (`qtech_backend`, `qtech_frontend`) and no `container_name`. The Postgres entrypoint re-syncs the superuser password with `psql -c` on every boot.
- **Entrypoint** (`backend/entrypoint.sh`):
  - runs `manage.py check --deploy` before `migrate`, with distinct messages for config failures and database failures;
  - runs migrate and collectstatic only in the Daphne container;
  - bootstraps the admin idempotently from `ADMIN_EMAIL` and `ADMIN_PASSWORD` (`ADMIN_FORCE_RESET` is optional);
  - seeds demo content only when `SEED_ON_DEPLOY=1`.
- **Gateway nginx** (`nginx/nginx.conf`, `nginx/Dockerfile`):
  - resolver `127.0.0.11` with a variable `proxy_pass`, so a redeploy produces no stale 502s;
  - `X-Forwarded-Proto` forced to https behind Cloudflare and Traefik; HSTS with preload;
  - `/ws/` timeouts of 86,400 s;
  - `/media/` served from the volume with immutable caching, a sandbox CSP and `nosniff`; `/media/_geo/` denied; `try_files` falls back to Django for missing renditions;
  - the SPA CSP is Report-Only with `unsafe-inline`;
  - COOP is `same-origin-allow-popups` for Google sign-in.
- **SPA nginx** (`frontend/nginx.conf`):
  - a crawler User-Agent map (`$is_social_crawler`) rewrites only crawlers to an internal prerender location;
  - a route whitelist turns soft 404s into a 301 to `/`;
  - `/m/` has its own fallback;
  - the service worker and manifest are served with `no-cache`.
- **Images.**
  - Backend: `python:3.11.3-alpine`, an old patch level, running as root, built with `pip --trusted-host`.
  - Frontend: built on `node:20-alpine` with `npm config set strict-ssl false` and `npm install` instead of `npm ci`.
- **Docs.** `DEPLOY.md` is an Arabic troubleshooting guide covering subnet exhaustion, port 80 being owned by Traefik, and domain collisions.

### 2.7 Scheduled jobs (Celery beat)

The schedule is code-defined in `CELERY_BEAT_SCHEDULE` and loaded into the DatabaseScheduler. All jobs run on a single default queue, with no retries, time limits or `acks_late` configured.

| Job | Schedule | Owner |
|---|---|---|
| GeoIP refresh (`core.tasks.refresh_geoip`, single-flight cache lock) | weekly | core |
| Chat cleanup (hard-delete soft-deleted messages older than 90 days) | daily | chat |
| Task reminder dispatch | every 5 min | tasks |
| Overdue task scan | hourly | tasks |
| Recurring task generation | every 6 h | tasks |
| Document expiry, contract expiry, probation-ending reminders | daily | hr |
| Attendance exception digest | every 12 h | hr |
| Missing check-out reminder | 20:00 | hr |
| Repeated lateness alert | weekly | hr |

`prune_analytics` exists but is **not** scheduled, so visitor analytics, including raw IPs, grow with no limit.

---

## 3. Apps in detail

**Legend.** Maturity:
- *production*: wired end to end, as far as the code shows;
- *partial*: works, but has clear gaps;
- *stub*: minimal.

Tests:
- *own*: tests in the app's own test files;
- *indirect*: covered by another app's tests;
- *none*.

### 3.1 `accounts` and `access`

**Models**
- `accounts.User`: custom email-login user (`AbstractBaseUser` + `PermissionsMixin`). Fields include:
  - a 6-value role enum: `super_admin`, `general_manager`, `manager`, `hr`, `employee`, `client`;
  - approval fields and soft-delete fields (`is_deleted`, `deleted_at`);
  - `email_verified`, `phone_verified`, `google_email`, and Telegram link fields.

  Managers: `objects = ActiveUserManager` hides deleted rows, and `all_objects` sees everything. `Meta.default_manager_name` and `Meta.base_manager_name` both point to `all_objects`, so DRF unique validators and FK lookups still see archived rows.
- `accounts.AuthSettings`: a singleton (pk forced to 1) that turns Google sign-in on and holds the public client ID.
- `access.RolePermission`: role × module view/edit override. Unique on (role, module_key).
- `access.UserPermissionOverride`: per-user override. HR also reuses it as a capability grant table. It has no expiry.

**Main endpoints**
- `/api/v1/auth/*`: login, refresh, verify, register, register-client, google, config, settings, test-email, verify-email, resend, password-reset.
- `/api/v1/me/*`: change-password, change-email, link-google, Telegram phone, HR and social profiles.
- `/api/v1/users/` with lifecycle actions.
- `/api/v1/access/*`: my-permissions, modules, matrix, user-overrides, audit, admin-overview, monitor, geodb.
- A Telegram webhook guarded by a secret.

| Feature | Maturity | Tests | Notes |
|---|---|---|---|
| JWT login with account-state error codes (`CustomTokenObtainPairView`) | production | none | HS256 signed with `SECRET_KEY`. Returns `email_not_found` vs `wrong_password`, so accounts can be enumerated by design. Successes and failures are audited with IP, user agent and country. |
| Two-axis brute-force throttling (`backend/core/throttling.py`) | production | none | Per real IP (`client_ip()` counts `NUM_PROXIES` from the right of `X-Forwarded-For`; `CF-Connecting-IP` is trusted only behind a flag). Per targeted email (`LoginTargetThrottle`, 8/min). Rates: login 10/min, register 5/min, password reset 5/min. |
| Google sign-in, GIS ID token (`GoogleLoginView`) | production | none | Checks `aud`, `iss` and `email_verified` through the tokeninfo endpoint, an HTTP call on every login. Toggled by `AuthSettings`. An archived account's email falls through to a create and raises IntegrityError (500). Google logins are not audited. |
| Google account link and unlink (`LinkGoogleView`, `GoogleLinkCard.vue`) | production | none | Returns 409 when the Google email already belongs to another account. Unlinking the last login method is not blocked. |
| Staff self-registration with admin approval | production | none | Case-insensitive duplicate check across all rows, including archived ones. |
| Client self-registration (instant login) | production | none | Split between client and staff audiences, specific to QTech. |
| Email verification | production | none | Stateless signed token (`django.core.signing`, 48 h). Resend gives a generic response. |
| Password reset and admin reset tools | production | none | Single use, because the token carries a fingerprint of the password hash. Admin `reset-link` returns a working link to the caller, which lets HR take over higher roles. Sessions are not revoked on reset. |
| Change password, change email | production | none | Both require the password; an email change triggers re-verification. Neither revokes sessions. |
| Telegram phone verification (`backend/accounts/telegram.py`) | production | none | `request_contact` button with a `contact.user_id == from.id` check. Short-lived deep-link code. Webhook secret compared with `hmac.compare_digest`. The webhook always returns 200. |
| Soft-delete recycle bin for users | production | none | Default-hidden manager plus `all_objects`. Restore, then purge; the purge writes its audit row before deleting. |
| Admin user lifecycle (`UserViewSet`) | production | indirect | Actions: approve, reject, suspend, reactivate, deactivate, set-role, reset tools, pending, deleted, restore, purge. **Suspend only sets `is_active=False`**: sessions and tokens are not revoked and no expiry is stored. `get_object()` protects only super-admin targets and lets you act on your own account; self-checks exist only in destroy, purge and the set-role demotion check. Most actions audit after `save()`. |
| Role hierarchy | production | indirect | One role column with helper properties. The `role` claim is in the JWT. |
| Module RBAC matrix (`access`) | production | indirect | About 45 module keys. Precedence: super-admin → per-user override → role row → code default. Every check recomputes the matrix (2 queries and a loop). `PermissionMatrixView.put` writes no audit, does not validate `module_key`, and loops without a transaction. Matrix editor UI: `AdminPermissions.vue`. |
| HR capabilities through the override table (`backend/hr/permissions.py has_cap`) | production | own (hr) | One DB lookup per miss, often inside loops. |
| Audit logging (`backend/core/audit.py record()`) | production | indirect | Never raises. Stores the raw IP, user agent and Cloudflare country. Four composite indexes. Read-only viewset with filters. `category` is free text; the taxonomy exists only as a frontend constant. |
| Monitor dashboard (`MonitorView`) | production | none | Sequential DB, Redis and Celery pings. The failed-login panel groups by a description string that contains the email, not by account id. |
| GeoIP database management (`GeoDatabaseView`) | production | none | Celery task with a lock and an inline fallback, plus a proxy-misconfiguration detector. |
| SMTP diagnostics (`EmailTestView`) | production | none | Super-admin test email that returns the exact exception. |
| WebSocket JWT middleware (`backend/core/ws_auth.py`) | production | none | Token in the query string; no `is_active` check. |
| Auto-create HR and Social profiles (`accounts/signals.py`) | production | indirect | Cross-app writes from a signal (monolith coupling). |
| Frontend auth and access stores (`stores/auth.js`, `stores/access.js`, `services/api.js`) | production | none | Single-flight refresh. On transient `/me` errors (429, 5xx, network) the session is kept by decoding the JWT. The last good permissions are cached in `localStorage`. |

### 3.2 `core`

**Models**
- `TimeStampedModel`, `UUIDTimeStampedModel`, `SoftDeleteModel`: abstract. `SoftDeleteModel` uses a QuerySet whose bulk `delete()` soft-deletes; `objects` hides binned rows and `all_objects` sees all.
- `AuditLog`, `PushSubscription`.
- Analytics: `VisitorLog` (one row per visitor per day), `PageHit` (per day and path), `VisitorSession` (UTM attribution, geo, device, bot flag), `PageViewEvent` (journey steps with dwell time).

| Feature | Maturity | Tests | Notes |
|---|---|---|---|
| Traffic attribution (`backend/core/attribution.py`) | production | none | Pure function. Order: UTM → ad click-id (fbclid, gclid, …) → android-app scheme → longest-suffix referrer host → direct. Internal referrers are relabelled direct in `tracking.py`. Includes the `is_bot()` UA marker list. |
| Session and journey tracking (`backend/core/tracking.py`, `frontend/src/composables/useVisitorTracking.js`) | production | none | Time is counted only while the page is visible. Flushes on `visibilitychange` (mobile often skips `pagehide`) and on `pagehide`, using `sendBeacon` with a JSON Blob. The server clamps dwell to 30 min and caps a session at 200 events. Each beacon causes about 7 Postgres queries. |
| Session analytics dashboard (`backend/core/session_analytics.py`) | production | none | Aggregates raw tables at request time. Super-admin only, and returns raw IPs. |
| Live visitors and daily aggregates (`VisitorTrackingMiddleware`, `backend/core/visitors.py`) | production | none | Redis ZSET plus a `SET NX EX` 15 s write cooldown. Per-day upserts with `F()`. Stores raw IPs. |
| Presence and per-user consumer | production | none | See section 2.3. |
| Versioned-namespace cache (`backend/core/cache.py`) | production | none | Defects: typo `cacheverison`, a get-then-set race, `cached()` ignores `ttl`, and `bump_version()` resets the version to 1 after the key is evicted, which can bring stale v1 entries back. |
| Soft delete and recycle bin (`backend/core/models.py`, `backend/core/trash.py`) | production | indirect (cms) | A `BIN_MODELS` registry spans cms and hr models. `purge` and `empty` are open to any staff member. |
| Real-client-IP throttles (`backend/core/throttling.py`) | production | none | `TrackPageView` uses DRF's stock `ScopedRateThrottle` instead, so the spoofable `X-Forwarded-For` prefix can be rotated to dodge it. |
| Web Push (`backend/core/push.py`, `push_api.py`) | production | none | Used only to ring offline callees. Prunes subscriptions on 404/410. Will not silently move an endpoint that belongs to another user. |
| GeoIP (`backend/core/geo.py`, `management/commands/update_geoip.py`, `backfill_geo.py`) | production | none | Cloudflare headers first, otherwise a DB-IP City Lite MMDB reopened when the file's mtime changes. The atomic download→validate→swap lives in `update_geoip.py`. Private IPs return empty before the Cloudflare header is read. Coordinates stay null rather than 0,0. |
| On-demand WebP renditions (`backend/core/images.py`, `image_views.py`) | production | none | Widths 400/800/1200/1600, quality 82, no upscaling (a rung equal to the source width is also skipped), EXIF transpose, a 50 MP decompression-bomb cap, atomic writes, a width whitelist and a path-containment check. nginx `try_files` falls back to Django. A docstring mentions an upload signal that does not exist. |
| HTML allowlist sanitizer (`backend/core/sanitize.py`) | production | none | BeautifulSoup allowlist. A second, divergent copy lives in `backend/cms/sanitize.py`. |
| CSP violation collector (`backend/core/csp.py`) | production | none | Unauthenticated, throttled at 60/min, 8 KB body cap, whitelisted fields, rotating `logs/csp.log`. |
| Settings hardening (`backend/qtech_config/settings.py`, `backend/core/checks.py`) | partial | none | Good: `_env()`/`_env_bool()` treat empty compose variables as unset; a 60 MB multipart guard and a 3 MB memory cap; system checks for SMTP sender and TLS mismatches. Bad: insecure defaults (section 5); `STATICFILES_STORAGE` is removed in newer Django. |
| Celery setup (`backend/qtech_config/celery.py`) | production | smoke only | One default queue. The entire Celery settings block sits inside `try/except`. |
| Chatbot engine (`backend/core/chatbot.py`) | production | none | Rule/FAQ bot built from CMS data, with an OpenAI-compatible fallback over `urllib`. `_norm()` handles Arabic normalization. |
| Branded email, CSV export, i18n field, UA parser (`email_utils.py`, `export.py`, `i18n.py`, `useragent.py`) | production | none | The CSV export writes a UTF-8 BOM (Excel then shows Arabic correctly) but does not escape spreadsheet formulas. `parse_ua()` has no "tv" class. |

### 3.3 `chat` and `notifications`

**Models (chat)**
- `Conversation`: types direct, group, department, announcement, support. Holds `can_access`, `can_post` and `can_manage`, and the support status.
- `ConversationMember`: role, mute, archive, `last_read_message`, `cleared_at`, soft leave.
- `Message`: UUID primary key, reply and forward self-FKs, soft delete.
- `MessageAttachment`: local `FileField` plus a thumbnail.
- `MessageReaction`, `MessageReadReceipt`, `ChatNotification`, `PinnedMessage`.

**Models (notifications)**
- `Notification`: dotted categories such as `hr.leave`.
- `NotificationSetting`: list of muted category prefixes.

| Feature | Maturity | Tests | Notes |
|---|---|---|---|
| Conversation authorization lives on the model | production | none | REST permissions, the consumer and the serializer all call `can_access`/`can_post`/`can_manage`. Private DMs and groups are membership-only, even for super-admins, yet `chat/admin.py` `MessageAdmin` shows them to Django superusers. |
| DM get-or-create (`services.get_or_create_direct`) | production | none | No unique constraint, so concurrent requests can create duplicate DMs. |
| Group chats, roles, system messages | production | none | Soft leave with reactivation. No last-owner guard: admins can demote or remove the owner. |
| Send with multiple attachments, reply, throttle, cursor history | production | none | 60/min per user, `CursorPagination` 30 per page (max 100). `CHAT_MAX_ATTACHMENTS_PER_MESSAGE` is defined but never enforced. |
| Edit, soft delete, restore, 90-day purge | production | none | No edit time window. The purge leaves files orphaned. `Message.restore()` brings back a message whose content was already wiped. |
| Forward | partial | none | Attachments are not copied, so a forwarded image arrives empty. |
| Reactions | production | none | The view enforces one reaction per user; the model's unique constraint allows several emojis. |
| Read state: pointer, read_by, peer ticks | production | none | `read_by` is derived from members' pointers. `mark_read` can move a pointer backwards. The list view prefetches every message, and unread counts run one COUNT per row. |
| Delivery ticks UI (`ChatMessageItem.vue`) | partial | none | "Delivered" is inferred from the peer being online, not from an acknowledgement. |
| Mute, archive, clear-for-me | production | none | `cleared_at` hides a conversation until a newer message arrives. Mute is not honoured in realtime pushes. |
| Pinned messages | production | none | |
| In-conversation and global search | production | none | `icontains` with no index. Email matching is deliberately excluded to prevent enumeration. |
| Shared-media panel | production | none | Up to 200 attachments, with signed URLs. |
| Attachments, signed URLs, thumbnails | partial | none | Validation is by extension only (SVG excluded). `ChatAttachmentView` (AllowAny) serves files inline with the client-supplied Content-Type. nginx serves `/media/chat/` publicly, which bypasses the signed URLs. Size limit is 100 MB in settings and 25 MB in the README. |
| Voice notes (`useVoiceRecorder.js`, `VoiceMessage.vue`) | production | none | Opus recording with a live level meter. The waveform is decoded in the browser for every bubble. |
| Per-conversation consumer | production | none | Membership is not re-checked after connect, so a removed member keeps receiving events until they reconnect. |
| Typing indicators | production | none | No rate limit. |
| Calls | partial | none | See section 2.4. |
| Client-support inbox | production | none | pending → open on the first staff reply → closed. The first responder auto-claims the thread. |
| Department and announcement channels | production | none | Coupled to HR. |
| `ChatNotification` fan-out rows | production | none | One row per recipient per message, which multiplies writes. |
| Offline email for new messages (`chat/tasks.py`) | partial | none | One email per message, with every recipient in a single `To:` header. |
| Unified notifications (`notifications/services.py notify()`) | production | none | Never raises. Category prefix muting (`hr` mutes `hr.*`) gates only the WebSocket toast; email ignores it. |
| Web Push for calls | partial | none | See section 2.4. |
| ASGI stack and socket auth | production | none | See section 2.3. |
| Messenger UI: page, dock windows, mobile screens | production | none | `ChatPage.vue` is a 779-line file. The thread logic is duplicated in `ChatWindow.vue`, `SupportChat.vue` and `mobile/screens/ChatRoomScreen.vue`. |

### 3.4 `social`

The app has 1,218 lines of Python and is mounted at `/api/v1/social/`. Every view is gated by `IsStaffMember`. There are no `services.py`, `tasks.py`, consumers or tests. Pushes run synchronously in the request.

**Models**
- `SocialProfile`: auto-created for staff by a signal.
- `Post`: visibility public / department / private / custom (with `allowed_viewers`), a free-text `feeling`, a `shared_post` self-FK, and `photo_kind` ('' / avatar / cover).
- `PostMedia`.
- `Comment`: `parent` is always the thread root; `reply_to` is the comment being answered.
- `Reaction`: 7 types; it targets either a post or a comment through two nullable FKs, with no check that exactly one is set.
- `SavedPost`, `Follow`, `Event`, `EventAttendance`.
- `Notification`: a legacy, verb-based table, merged with the `notifications` app in the SPA.

| Feature | Maturity | Tests | Notes |
|---|---|---|---|
| Ref-counted multi-tab presence | production | none | Implemented in core (section 2.3). |
| Two-level comment threads | production | none | Replies to replies are re-parented onto the thread root, and both the post author and the answered comment's author are notified. `parent` stays writable with no same-post check (cross-post replies). `get_replies` runs one query per root. The mention link in `CommentList.vue` passes a comment id as a user id. |
| Comment reactions | partial | none | `reaction_type` is not validated; values over the length limit raise a DataError (500). Comment reactions send no notification. |
| Post reactions and who-reacted list | production | none | Breakdown and `my_reaction` are computed per post (N+1). Counts are broadcast to the global group. |
| Home feed, pull model, infinite scroll | production | none | IN(list) + OR + DISTINCT with page-number pagination; does not scale. Deep link to a post with highlight. |
| Post audiences, including department and custom | partial | none | `allowed_viewer_ids` are not validated. |
| Quote-share with root flattening and who-shared list | production | none | A share is notified with the wrong verb (`MENTION`). |
| Profile photo as a post | production | none | `GET /posts/profile-photo/` creates rows during a GET and accepts any `user_id`. |
| Photo theater and media grid (`PostFeed.vue`) | production | none | Grid layouts for 1, 2, 3 (one tall plus two stacked) and 4+ with a "+N" overlay. The viewer is URL-backed (`?view=<postId>`, so Back closes it), with swipe, arrow keys and a thumbnail strip. `?view=` holds only the post id, so a refresh reopens the post at image 0. Swipe and arrows are not RTL-aware. Videos render as `<img>`. Dates are ISO strings sliced to 10 characters. `PhotoViewer.vue` is a separate single-image viewer. |
| Live feed updates | production | none | `post.new` goes to followers or allowed viewers. Count events for **all** posts, private ones included, go to the global group. |
| Follow graph and people directory | production | none | `followed_ids` is put in the serializer context, but the same serializer still runs per-row COUNTs. Suggestions have no ranking. |
| Events and RSVP | partial | none | Toggle RSVP, counts from one GROUP BY. `is_public` is never enforced; the status is not validated; the attendees list is unpaginated and visible to all staff. |
| Saved posts | partial | none | The saved-list endpoint has no frontend caller. |
| Feeling | production | none | Stores the localized label (for example "😊 سعيد") instead of a stable key. |
| Social notifications | production | none | Skips self-actions. Fires before commit. |
| Profile privacy masking | production | none | `to_representation` drops email, phone and birth date for other viewers. |
| Upload validation | production | none | Extension and size only. Video and image are chosen from the client's content type. |
| **Profile posts IDOR** (`SocialProfileViewSet.posts`) | — | none | Returns a colleague's private, department-only and custom-audience posts (see section 5). |

### 3.5 `cms`

The app has about 5.6K lines of non-migration Python, 28 models, 42 migrations and the best test file in QTech.

**Models**
- `SiteSettings`: a singleton with about 150 bilingual copy fields, feature flags, section order and chrome JSON.
- Landing collections: `NavLink`, `WhyCard`, `ExpertiseItem`, `ProblemCard`, `Service`, `Testimonial`, `Stat`, `Partner`, `FAQ`, `TeamMember`.
- Portfolio: `ProjectCategory`, `Project`, `ProjectNote` (a `CheckConstraint` requires exactly one target), `ProjectImage`.
- Store: `Product` (nullable price, `sale_price`, `Currency` choices), `ProductImage`.
- `BlogPost`, `ContactMessage`, `NewsletterSubscriber`.
- Chatbot: `ChatbotConfig`, `ChatbotSession`, `ChatbotMessage`, `ChatbotLead`.
- `AppRelease`.
- Page builder: `Page` (live `blocks` plus `draft_blocks`, SEO fields), `PageRevision`.
- `MediaAsset`.

| Feature | Maturity | Tests | Notes |
|---|---|---|---|
| Block-based page builder (`backend/cms/blocks.py`, `AdminPages.vue`, `BlockRenderer.vue`) | production | own | 15 block types. The catalogue is served by the server and the editor builds its forms from it. Validation is strict on the envelope and forgiving on props, with a depth cap of 3 that raises rather than trims. Rich text is sanitized on write. URL and image props are unvalidated strings. |
| Draft, publish, revision workflow | production | own | Snapshot before overwrite; restore goes into the draft, never live; discard can be undone; a duplicate is always a draft. `publish` has no `transaction.atomic`. |
| HTML allowlist sanitizer (`backend/cms/sanitize.py`) | production | own (8 XSS cases) | Strips control characters before the scheme check; forces `rel=noopener`. Diverges from the core copy. |
| Media library and block upload | partial | own (2) | UUID filenames, 12 MB cap, Pillow dimensions. SVG is allowed. The library can be listed anonymously and leaks uploader emails. |
| SEO: robots, sitemap, Search Console file, GA/GTM, per-page meta | partial | none | Block pages are missing from the sitemap. No sitemap index. |
| Crawler link previews (`backend/cms/social.py`) | production | none | Head-only HTML with escaped OG, Twitter and canonical tags; JSON-LD Product with an Offer only when the item is priced. The JSON-LD is written without escaping `<`. `og:url` and canonical are built from the internal path. `throttle_classes = []`. |
| Blog | partial | none | Admin authoring looks broken: create and update use the list serializer, which drops the body, and the admin PATCHes by id while the lookup field is the slug. `published_at` is set only on create. The view counter is not atomic. |
| Portfolio projects with internal pipeline and notes | production | none | One record serves two audiences through separate serializers. Annotated counts. |
| Store products | production | none | `null` price means "on request" and `0` means free. Sorted by `Coalesce(sale_price, price)` with unpriced items last. A facets endpoint. `sale_price < price` is never enforced. |
| Landing aggregation with versioned cache | production | none | One 600 s cached payload per language. |
| Site chrome builder (`backend/cms/chrome.py`) | production | none | A JSON settings document validated against a catalogue. No number kind. Unknown keys are silently dropped. No URL validation. |
| SiteSettings singleton | production | none | Specific to the company website. |
| Contact inbox | production | none | List, detail and CSV export are **anonymously readable** (section 5). |
| Newsletter | partial | none | No double opt-in and no unsubscribe token. Sending is synchronous. List and export are anonymously readable. |
| Website chatbot | partial | none | Blocking LLM call inside the request. API key stored in plaintext in the DB (write-only through the API). Client-supplied history is trusted. |
| App release changelog / "what's new" | production | none | |
| Nav links, landing collections | production | none | Inactive testimonials, stats, partners and FAQs can be reached through the API. |
| Video | stub | none | Only an unvalidated `hero_video` FileField and a YouTube/Vimeo embed block. |
| Soft delete / recycle bin integration | production | own (pages/media) | |

### 3.6 `billing` and `theming`

**Models**
- billing: `ClientProject`, `ProjectDeliverable`, `Invoice`, `InvoiceItem`.
- theming: `ThemeSettings` (singleton), `UserTheme`.

| Feature | Maturity | Tests | Notes |
|---|---|---|---|
| Client billing: projects, deliverables, invoices, CSV, print | partial | none | No payment gateway anywhere in the backend. The invoice number is filled by a post-insert UPDATE on a unique blank column, so concurrent creates collide. Items are replaced without a transaction. No status state machine. Money is quantized to 0.01. `subtotal` is N+1. Deliverables are served publicly under `/media/`. |
| Theming: global theme, per-user overrides, WCAG contrast maths (`frontend/src/stores/theme.js`) | production | none | The contrast functions (`contrast`, `inkFor`, `forDarkSurface`, `scrimFor`) are solid. Values are not validated on the server, and `radius`, `login_gradient` and `font_family` are written raw into a `<style>` element, which allows CSS injection by anyone who can edit the appearance. |

### 3.7 `hr` and `tasks`

**Models (hr, 48)**
- Organization: `Department`, `CompanyEntity`, `Branch`, `Grade`, `Designation`, `WorkSchedule`, `HRProfile`, `Holiday`.
- Time: `Attendance`, `ShiftTemplate`, `ShiftAssignment`, `AttendanceCorrection`, `Timesheet`, `TimesheetEntry`.
- Leave: `LeaveType`, `LeaveRequest`, `LeaveBalance`.
- Approvals: `ApprovalWorkflow`, `ApprovalStep`, `HRRequest`, `ApprovalAction`.
- Documents and assets: `EmployeeDocument`, `EmploymentContract`, `AssetCategory`, `Asset`, `AssetAssignment`.
- Onboarding: `OnboardingTemplate`, `OnboardingRecord`, `OnboardingItem`.
- Recruitment: `JobOpening`, `Candidate`, `JobApplication`, `Interview`, `InterviewFeedback`, `Offer`.
- Performance: `PerformanceCycle`, `PerformanceReview`, `Goal`, `Objective`, `KeyResult`.
- Training: `TrainingCourse`, `TrainingEnrollment`.
- Pay: `CompensationRecord`, `PayrollPeriod`, `PayrollRecord`.
- Dashboards and announcements: `HRDashboardLayout`, `HRWidgetPreference`, `Announcement`.

**Models (tasks, 17)**
- `Team`, `TaskProject`, `TaskBoard`, `TaskColumn`, `TaskLabel`.
- `Task`: UUID primary key, 7 visibility levels, 9 statuses.
- `TaskAssignee`, `TaskSubtask`, `TaskChecklist`, `TaskAttachment`, `TaskComment`, `TaskActivityLog`, `TaskDependency`, `TaskReminder`, `TaskTemplate`, `TaskDashboardLayout`, `TaskWidgetPreference`.

| Feature | Maturity | Tests | Notes |
|---|---|---|---|
| Recruitment / ATS backend | partial | none | 8-value stage enum, unique (job, candidate), interview panel, one scorecard per panelist, offer 1:1. Stage changes can go through a POST action **and** through PATCH, because the serializer leaves `stage` writable and `HrRecruitment.vue` itself uses PATCH. The stage action allows any stage to any stage. Rating has no range constraint. `panelist` is `SET_NULL`, which breaks the unique constraint once a panelist is deleted. Interviews, offers, candidates and convert have no frontend callers. |
| Public careers board and apply (`backend/hr/careers.py`, `CareersPage.vue`) | production | none | Open-only list and detail, apply with get_or_create (an "already applied" 200 vs 201), resume validation. The throttle scope `register` is shared with sign-up. The Candidate is looked up by email and overwritten, unauthenticated. No race handling. The modal is not accessible. |
| Recruiter pipeline Kanban (`HrRecruitment.vue`) | partial | none | Responsive stage columns with an optimistic move and rollback. No drag-and-drop. The stage list omits "withdrawn". Loads 200 applications at once. Reads a `candidate_resume` field the API never returns. |
| Task visibility engine (`backend/tasks/visibility.py`) | production | own (8) | One function builds the permitted queryset, and `user_can_view()` calls it on a single row. The "consistency" test is tautological. |
| Role-to-capability permissions (`hr/permissions.py`, `tasks/permissions.py`) | production | own | Named capabilities plus per-user grants. Uncached DB lookups. Duplicated across the two apps. |
| Field-level stripping and write-locking (`backend/hr/serializers.py`) | production | none | Salary and sensitive fields are removed per viewer; privileged fields are read-only for non-HR users. Capability checks run per row. |
| Configurable multi-step approval engine (`backend/hr/approvals.py`) | partial | none | Workflow plus step pointer plus an immutable action log. No row lock. `my_approvals` filters in Python. No configuration UI. |
| Widget dashboard registry | partial | own | Duplicated in hr and tasks. The frontend never calls it. |
| Reports and analytics endpoints | production | own | Computed over the caller's permitted queryset. |
| Task status workflow with gates | production | none | Completion is gated on checklist, dependencies and approval, but **PATCH bypasses the gates** (section 5). Lists use cursor pagination and annotated counts. |
| Task realtime events | partial | none | Sent only to related users. The frontend does not subscribe. |
| Recurring task generation | production | none | No unique constraint per period, so overlapping workers can create duplicates. "weekdays" hard-codes Mon–Fri. |
| Reminder dispatch and overdue scan | partial | none | Not safe under concurrency. No API creates reminders. |
| HR scheduled reminders | production | own (smoke) | Expiry reminders are idempotent through flags. |
| Soft delete for job openings | production | none | Uses core `SoftDeleteModel`; tasks use a different, hand-rolled style. |
| Schema-driven CRUD admin UI (`HrCrud.vue`, `config/hrSchemas.js`) | production | none | A new admin screen is a schema entry. |
| Task Kanban with drag-and-drop (`TasksBoard.vue`) | partial | none | Built on vuedraggable. The UI state can drift from the server's state. |
| Org chart, directory, CSV export, reference data | production | own (helpers) | |
| Attendance, shifts, timesheets, leave, payroll, assets, onboarding, OKRs, training | production / partial | mostly none | Company HR; nothing here for Tara. Re-approving a leave deducts the balance twice. |

### 3.8 Frontend modules not tied to one backend app

| Module | Maturity | Tests | Notes |
|---|---|---|---|
| Mobile PWA shell (`src/mobile/*`) | production | none | `useSwipeBack.js`: back gesture from the leading edge, flipped for RTL (RTL assumed unless `dir` is ltr). `PullToRefresh.vue` (on `window.scrollY`). Push and pop transitions. `UpdateBar.vue` waiting-worker handshake. KeepAlive tabs. Idle prefetch. Uses Arabic literals rather than vue-i18n. |
| Web Push (`composables/usePush.js`, `mobile/push.js`) | production | none | The mobile flow never asks for permission on load; it re-attaches silently on boot when permission is granted and unsubscribes locally first. The desktop flow asks on login. |
| Unified notifications inbox (`composables/useNotifications.js`, `NotificationBell.vue`) | production | none | Upserts by id, builds deep links, offers inline approve/reject. Unread is computed from loaded items only. |
| Module registry and permission matrix UI (`config/nav.js`, `ModuleHost.vue`, `AdminPermissions.vue`) | production | none | |
| Admin monitor and visitor map (`AdminMonitor.vue`, `VisitorMap.vue`) | production | none | Polls every 15 s, paused while the tab is hidden. TopoJSON map with no extra library. |
| Responsive images (`components/ui/SmartImage.vue`, `utils/media.js`) | production | none | |
| Generic UI kit | production | none | `AppModal` has no dialog role and no focus trap. |
| Charts (`ChartLine.vue`, `ChartDonut.vue`) | production | none | Hard-coded colours; no dark mode or RTL handling. |
| Page meta (`composables/usePageMeta.js`) | production | none | |

---

## 4. Tech patterns

These patterns recur across QTech. The ones worth keeping are marked with **(keep)**; the ones Tara has rejected for good reason are marked with **(avoid)**.

- **(keep)** Authorization methods on the domain model (`Conversation.can_access/can_post/can_manage`), shared by DRF permissions, the consumer and the serializer flags.
- **(keep)** One visibility function per entity, reused for both list and detail views (`tasks/visibility.py`). The social app breaks this pattern in `SocialProfileViewSet.posts`, and that is where its IDOR comes from.
- **(keep)** Field-level stripping in `to_representation` together with write-locking in the serializer `__init__`.
- **(keep)** Server-owned schema catalogues served to the UI (`cms/blocks.py`, `cms/chrome.py`), so admin forms are generated and never duplicated on the client.
- **(keep)** Live and draft JSON fields with snapshot-before-overwrite revisions.
- **(keep)** Soft delete with two managers. `objects` hides deleted rows and `all_objects` sees everything. `default_manager_name` and `base_manager_name` both point to the full manager.
- **(keep)** Redis presence: a heartbeat sorted set plus `HINCRBY` socket counting. Presence events fire only on the first and last socket.
- **(keep)** Pointer-based read state (`last_read_message`) and per-member "clear for me" (`cleared_at`).
- **(keep)** A visibility clock for dwell time, sent with `sendBeacon` as a JSON Blob and clamped on the server.
- **(keep)** Priority-ordered attribution: UTM → click-id → app scheme → referrer → direct.
- **(keep)** An MMDB reader hot-reloaded on file mtime. Celery single-flight via `cache.add(key, ttl)`. Atomic file writes via a temp file and `os.replace`.
- **(keep)** The real client IP is counted `NUM_PROXIES` from the right of `X-Forwarded-For`. A second login throttle counts per targeted account.
- **(keep)** Django system checks and `check --deploy` run before migrate. Empty compose variables are treated as unset.
- **(keep)** Crawlers are detected by User-Agent at the edge and served a prerendered OG head from an internal location.
- **(keep)** CSP is shipped as Report-Only first, with an in-app collector.
- **(keep)** Logical (start/end) Tailwind utilities for RTL. Overlay state lives in the URL, so Back closes it.
- **(keep)** WCAG contrast maths that derives readable colour roles from a user-chosen accent.
- **(avoid)** Synchronous `group_send` inside HTTP requests, with no outbox and no `on_commit`.
- **(avoid)** Side effects wrapped in a broad `try/except: pass`. Failures disappear silently.
- **(avoid)** Bilingual content stored as paired `_ar`/`_en` columns. This suits admin-curated reference data, not user content.
- **(avoid)** Module-singleton composables holding shared state that is never reset on logout.
- **(avoid)** One socket per open conversation, plus a global broadcast group joined by every socket.
- **(avoid)** Local `FileField` storage served by nginx from a public `/media/`, with extension-only validation.

---

## 5. Security observations

All findings come from **reading the code**. None was exploited or executed. Tara must not copy any of the patterns below. Lines marked "privacy" are data-protection issues rather than direct exploits.

| Severity | Finding | Where (QTech) | Lesson for Tara |
|---|---|---|---|
| Critical | Contact messages and newsletter lists and CSV exports are readable without logging in. `ContentEditGate` allows every SAFE method, and neither viewset narrows its queryset. | `backend/cms/views.py` (`ContactMessageViewSet`, `NewsletterViewSet`) | Read access to private resources needs its own permission, never "staff or read-only". |
| High | Any caller, possibly unauthenticated, appears able to read any user and the pending list (email, phone, Google email, nested HR profile with national id and address). `IsSelfOrCanManage` does not override `has_permission`, and returns True for SAFE methods. Ids are sequential. | `backend/accounts/views.py`, `backend/accounts/permissions.py` | Always implement `has_permission`; use UUIDs; test anonymous access. |
| High | HR can create a `super_admin` account, because `role` is writable on create with no validation. | `backend/accounts/serializers.py` (`AdminUserCreateSerializer`) | Role assignment goes through one guarded path only. |
| Medium | HR can take over a general manager account: `reset-link` returns a working link, or HR can PATCH the GM's email and then reset the password. | `backend/accounts/views.py` (`UserViewSet`) | Act only on accounts of a lower role; never return reset links to staff. |
| High | Published pages leak `draft_blocks`, `updated_by` and `deleted_by` to anonymous readers. | `backend/cms/serializers.py` (`PageSerializer` uses `exclude`) | Separate public and editor serializers with explicit field lists. |
| High | The media library can be listed anonymously and exposes uploader names and emails. | `backend/cms/views.py` (`MediaAssetViewSet`), `serializers.py` | |
| High | Profile timelines return a colleague's private, department-only and custom-audience posts (IDOR). | `backend/social/views.py` (`SocialProfileViewSet.posts`) | Every list goes through the visibility function; add a matrix test. |
| High | LiveKit room hijack: the room name in the token is taken from the client. | `backend/chat/views.py` (`call_token`) | Build room names on the server from an authorized call. |
| High | Unauthenticated call relay: any staff member can push arbitrary `call.*` payloads to any user id, including Web Push to offline users. | `backend/core/consumers.py` | Check shared conversation and block state before relaying. |
| High | Possible stored XSS: chat attachments are served inline with the Content-Type the client supplied at upload, from the app origin. | `backend/chat/views.py` (`ChatAttachmentView`) | Use `Content-Disposition: attachment`, a server-detected MIME type, and a separate origin. |
| High | Signed attachment URLs are bypassable: nginx serves `/media/` (including `/media/chat/` and billing deliverables) publicly, and original filenames are kept. | `nginx/nginx.conf`, `backend/billing/models.py` | Private files go only through authorized presigned URLs. |
| High | A default VAPID private key and public key are committed as `config()` defaults (values not reproduced). | `backend/qtech_config/settings.py` | Secrets come from env only, with no default; rotate if ever exposed. |
| High | Insecure defaults: a fallback `SECRET_KEY`, `DEBUG` and `LOCAL` both default to True, and production `ALLOWED_HOSTS` defaults to `*`, which disables the WebSocket origin check. A missing env var silently runs DEBUG on SQLite. | `backend/qtech_config/settings.py` | Fail fast in deploy checks (Tara already does this). |
| High | One secret signs everything: JWTs are HS256 with `SECRET_KEY`, which also signs the verification and reset tokens. | `backend/qtech_config/settings.py`, `backend/accounts/emails.py` | RS256 + JWKS for user tokens (Tara has this). |
| Medium | Tokens live in `localStorage`. The WebSocket token travels in the query string, where it ends up in proxy logs. `ws_auth` ignores `is_active`, and sockets outlive token expiry. | `frontend/src/services/api.js`, `frontend/src/services/ws.js`, `backend/core/ws_auth.py` | |
| Medium | No session revocation when the password changes, the password is reset, the email changes, or an account is suspended. 14-day refresh tokens keep working. | `backend/accounts/views.py` | Revoke every refresh family on these events. |
| Medium | Account enumeration at login (`email_not_found` vs `wrong_password`). | `backend/accounts/serializers.py` | Reveal account state only after the password has been verified. |
| Medium | Task approval gates can be skipped with a PATCH (`status`, `requires_approval`), because `update()` does not pop them as `create()` does. | `backend/tasks/views.py`, `backend/tasks/serializers.py` | State changes go only through guarded actions. |
| Medium | Watcher injection: an editor can add any user as a watcher, which grants visibility of confidential tasks. | `backend/tasks/views.py` (`add-watcher`) | |
| Medium | Unauthenticated candidate tampering: applying with someone's email overwrites their name, phone and resume. | `backend/hr/careers.py` | Applications must be authenticated and owned. |
| Medium | `convert` matches a candidate to an existing account by an unverified email and overwrites that user's HR fields. | `backend/hr/views.py` (`JobApplicationViewSet.convert`) | |
| Medium | Cross-post comment parent, plus unvalidated enums (`reaction_type`, RSVP status): arbitrary strings are stored, and long ones cause a 500. | `backend/social/views.py`, `serializers.py` | Use `ChoiceField`; derive the post from the parent. |
| Medium | Possible stored XSS through page-builder URL props and nav or chrome links, which allow `javascript:` URLs. | `backend/cms/blocks.py`, `backend/cms/chrome.py`, `BlockRenderer.vue` | Validate URL schemes on the server. |
| Medium | Active content can be uploaded and served from the same origin: SVG in block uploads, HTML for product showcases, an unvalidated hero video. | `backend/cms/views.py` (`BlockUploadView`), `backend/cms/models.py` | Separate media origin, MIME sniffing, never serve HTML or SVG inline. |
| Medium | The offline-message email lists every recipient in one `To:` header. | `backend/chat/tasks.py` | One message per recipient. |
| Medium | Any staff member can permanently purge or empty the recycle bin. | `backend/core/trash.py` | |
| Medium | Static TURN credentials are compiled into the public frontend bundle. | `frontend/src/composables/useMeshCall.js` | Short-lived TURN credentials minted by the API. |
| Medium | The PWA service worker caches authenticated API responses keyed only by URL and never clears them. The global socket is not closed on logout. | `frontend/public/app-sw.js`, `HubLayout.vue` | Never cache private API data; tear down sockets and stores on logout. |
| Medium | Supply chain: `pip --trusted-host`, `npm strict-ssl false`, `npm install` without lockfile enforcement, an old Python patch level, containers running as root, and dev tools in `requirements.txt`. `Pipfile` and `requirements.txt` disagree on versions. | `backend/Dockerfile`, `frontend/Dockerfile` | |
| Medium (privacy) | Presence is broadcast to a global group joined by every socket, clients included, and `OnlineUsersView` returns every online user id. | `backend/core/consumers.py`, `backend/chat/views.py` | Send presence only to authorized peers. |
| Medium (privacy) | Raw IPs are stored in analytics and audit rows, failed-login descriptions contain the raw email, and the retention job is not scheduled. | `backend/core/models.py`, `backend/core/audit.py` | Tara stores only a coarse region. |
| Low | CSS injection through theme fields written raw into `<style>`. | `frontend/src/stores/theme.js`, `backend/theming/*` | Validate colours and tokens strictly on the server. |
| Low | Upload validation is by extension only, with no magic-byte check. | `backend/core/validators.py`, `backend/chat/validators.py` | |
| Low | Swagger and ReDoc are public in every environment. | `backend/qtech_config/urls.py` | |
| Low | Hard-coded demo credentials in `seed_demo` and in the untracked `frontend/_shot.mjs` (values not reproduced). | `backend/core/management/commands/seed_demo.py`, `frontend/_shot.mjs` | |
| Low | The Postgres password is re-synced with `psql -c` on every boot, which puts it in process arguments. | `docker-compose.prod.yml` | |
| Low | The chatbot API key is stored in plaintext in the database, and chat history supplied by the client is trusted. | `backend/cms/models.py` (`ChatbotConfig`), `backend/core/chatbot.py` | |
| Low | The page-view throttle uses DRF's stock IP logic; rotating the `X-Forwarded-For` prefix bypasses it. | `backend/core/analytics.py` | |
| Low | The permission matrix and per-user overrides are written without audit or key validation. `MessageAdmin` exposes private DMs to Django superusers. | `backend/access/views.py`, `backend/chat/admin.py` | |

**Good practices worth keeping:**
- Generic responses on password-reset and resend-verification requests.
- Changing the email requires the password.
- Google linking refuses an identity that is already tied to another account.
- The Telegram webhook compares its secret in constant time and accepts a contact only when it belongs to the sender.
- Purge is allowed only on archived accounts, and the audit row is written first.
- Private DMs and groups are membership-only even for super-admins.
- UUIDs on conversations and messages; a per-user send throttle; email excluded from staff search.
- Chat links are escaped first, then linkified (https only).
- Push-subscribe will not move another user's endpoint.
- SVG is excluded from chat and social uploads.
- Uploaded media gets a sandbox CSP and `nosniff` at nginx.
- Renditions use a width whitelist plus a realpath containment check.
- Real IPs are counted from the right of `X-Forwarded-For`.
- A per-account login throttle.
- An explicit upload size guard; `page_size` capped at 100.
- `.env`, `.env.production` and `db.sqlite3` are not tracked in git.

---

## 6. Tests and quality

| Area | What exists |
|---|---|
| Backend tests | 3 files, 10 classes, 70 test functions. `backend/cms/tests_pages.py`: 48 tests (PageAPITests 22, BlockValidationTests 5, SanitizerTests 8, MediaLibraryTests 2, NestingTests 11). `backend/hr/tests.py`: 10 tests (capabilities, account lifecycle with AuditLog, report gating, reminder smoke). `backend/tasks/tests.py`: 12 tests (visibility matrix, assign capabilities). |
| Untested | accounts, access (indirect only), chat, consumers, calls, LiveKit token, notifications, social, billing, theming. Almost all of core is untested: ws_auth, presence, push, throttling, renditions, trash, CSP, visitors, geo. Also untested: the contact/newsletter leak, blog, products, SEO, chatbot. |
| Likely stale assertion | `RoleCapabilityTests.test_employee_cannot_assign_to_manager` asserts `can_assign(manager, employee)` is True. The setup gives the manager no department, reports or teams, so the call should return False. |
| Frontend tests | None. There is no vitest or jest config and no spec files. Playwright is used only by `frontend/_shot.mjs`, a screenshot script with no assertions. axe-core is installed but unused. |
| CI | None (no `.github/workflows` or any other pipeline). |
| Test database | Tests default to SQLite, because `LOCAL` defaults to True. |
| Migrations | 106 in total: cms 42, hr 14, accounts 13, theming 11, social 9, core 6, chat 5, access 2, notifications 2, billing 1, tasks 1. |
| Run during this audit | **No.** QTech was treated as read-only and nothing was executed. |

Anything ported to Tara needs new tests in Tara's harness (`scripts/test-service.sh`, vitest, Playwright). Most of the reusable code is pure logic and easy to test: `attribution.resolve`, `tracking` clamps, `client_ip`, cache versioning, the sanitizers, `geo.lookup` precedence, the theme contrast functions, `_norm`, and the price semantics.

---

## 7. QTech compared with Tara

| Concern | QTech | Tara today |
|---|---|---|
| Architecture | Monolith with one DB; cross-app FKs, signals and lazy imports | 14 Django/DRF services plus a FastAPI BFF; one DB per service; no shared tables |
| Cross-service effects | Synchronous `group_send` and `notify()` inside the request | Transactional outbox, RabbitMQ, retry and DLQ, idempotent consumers |
| User auth | HS256 with `SECRET_KEY`; refresh rotation + blacklist | RS256 + JWKS; opaque rotating refresh tokens with family reuse detection; roles claim |
| Presence | Ref-counted across tabs, with `last_seen`, but broadcast to everyone | One cache key per account: closing one tab marks the user offline, ping does not refresh it, and nothing reads it |
| Voice/video calls | LiveKit SFU plus mesh fallback (partial; insecure token and relay) | None |
| Crawler link previews | UA map plus prerendered OG head | None (crawlers get the SPA shell) |
| Media | Local filesystem; on-demand WebP renditions | MinIO with presigned URLs; 320 px thumbnail only; no video processing |
| Social extras | Events/RSVP, comment reactions, profile photos as posts, Facebook-style grid and theater | Not present |
| Recruitment | Full ATS model (backend partial, UI partial) | No professional service; profiles have work and education only |
| Staff permissions | Layered module matrix with per-user overrides | Coarse roles claim (admin, moderator, ad_reviewer, analyst) |
| Frontend | Plain JS; ar/en parity but many hard-coded Arabic strings | Vue 3 + TypeScript + Pinia; ar/en parity test; Arabic RTL default |
| Tests and CI | 70 backend tests, no frontend tests, no CI | 15 green service suites, vitest about 127 cases, Playwright about 50 tests, CI (the frontend job only builds) |
| Observability | Health pings, CSP collector, file logs | Prometheus, Grafana and OTel in dev (not yet on Dokploy) |

**Bottom line.** Tara's platform foundations are well ahead of QTech's: auth, events, data ownership, tests and CI. QTech is ahead on product features: calls, presence correctness, link previews, events, the photo theater and recruitment. That is why section 8 takes QTech's product designs and reimplements them on Tara's foundations, rather than porting QTech code wholesale.

---

## 8. Reusable for Tara

**How to read this table**
- **Value** is the value *after* verification, on a scale of High, Medium and Low.
- **Verdict** comes from the verification pass:
  - **Confirmed**: the code exists as described and the reuse plan holds.
  - **Overstated**: the code exists but is weaker or less reusable than first claimed; the note gives the corrected picture.
  - **Not re-verified**: described by the area audits but not re-opened by the verification pass.
  - **Not reused**: Tara already has something better, or a module design rejected the idea.
- Where several Tara module designs assessed the same QTech asset, the verdicts are merged into one row and any differences are stated.

### 8.1 Realtime, messenger and calls

| # | Feature | QTech files | Value | Verdict | What to take, and corrections | Tara target |
|---|---|---|---|---|---|---|
| 1 | LiveKit SFU deployment | `infra/livekit/docker-compose.yml`, `infra/livekit/livekit.yaml`, `infra/livekit/README.md` | High | Confirmed | Take the separate compose with inline config and keys from env, one UDP port (50000) plus TCP 7881, and the firewall and DNS runbook. It has no webhook, no TURN and no room limits. A same-origin `/rtc` proxy in Tara would be new, untried work. | Messenger calls |
| 2 | Call-token and active-call endpoints | `backend/chat/views.py` (`call_token`, `call_start`, `active_call`, `call_log`) | High (shape only) | Confirmed | Take the endpoint shapes and the 503-when-unconfigured fallback. Do not copy the room name from `request.data` (hijack), the call log built from client-supplied status, or the hand-rolled 6 h PyJWT token. | Messenger calls |
| 3 | LiveKit client engine | `frontend/src/composables/useLiveKitCall.js`, `useCall.js` | High | Confirmed | Take the Room event binding, the participant model, the active-speaker set, the no-answer timer and the ringtone. Discard the static import, `Number(identity)`, client-generated room names, and the `call.end` handler that ignores the room. `useCall.js` is 15 lines and adds little. | Messenger calls |
| 4 | Call UI and ringing options | `frontend/src/components/chat/CallOverlay.vue`, `CallPicker.vue`, `frontend/public/sw.js` | Medium | Overstated | `CallOverlay.vue` layout logic is worth porting. `CallPicker.vue` searches the global staff directory and does not fit. The service-worker call options are about 5 lines with one static tag. No focus trap. | Messenger calls |
| 5 | P2P mesh engine | `frontend/src/composables/useMeshCall.js` | Low | Not reused | Glare rollback and one-sided ICE restart are good ideas, but the Messenger design drops mesh: static TURN credentials in the bundle, and it does not scale. | — |
| 6 | Multi-tab presence | `backend/core/realtime.py`, `backend/core/consumers.py`, `frontend/src/composables/usePresence.js` | High | Confirmed | Take the heartbeat sorted set (70 s), per-socket counting, `last_seen`, and the client's seed, delta and 30 s re-seed. The connection-count hash has no TTL, so a crashed gateway leaves the count above zero and the offline event never fires. Ids are `int()`-cast. Do not take the global `feed` broadcast or the "all online ids" endpoint. | Realtime, messenger |
| 7 | Pointer read state and clear-for-me | `backend/chat/models.py`, `views.py`, `serializers.py` | Medium | Confirmed | Take `cleared_at` semantics and `read_by` derived from pointers. Do not copy the full-message prefetch, the per-row unread COUNT, or the non-monotonic `mark_read`. | Messenger |
| 8 | Thread rendering details | `frontend/src/components/chat/ChatMessageItem.vue`, `frontend/src/pages/app/modules/ChatPage.vue` | Medium | Confirmed | Take emoji-only sizing, viewport-clamped popovers, day dividers with 5-minute grouping, jump-to-message, and the "new below" counter. Times are hard-coded to `ar-EG` and day labels use the browser locale. Jump paging becomes redundant once an `?around=` endpoint exists. | Messenger |
| 9 | Forward, edit and soft-delete semantics | `backend/chat/views.py`, `models.py`, `permissions.py`, `tasks.py` | Medium | Confirmed | Take the two-sided permission check on forward, owner-only edit, content-wiping soft delete, and the retention purge. Forward copies no attachments. Do not port `Message.restore()`, which un-deletes wiped content. | Messenger |
| 10 | Voice-note waveform | `frontend/src/components/chat/VoiceMessage.vue` | Low | Overstated | It downloads and decodes every note when the bubble mounts; a 10-minute note is over 100 MB of PCM on mobile. Compute the peaks on the server. | Messenger |
| 11 | Toast suppression for the open conversation | `frontend/src/composables/useMessages.js` | Low | Overstated | Tara's `App.vue` already skips toasts for the open conversation. Only the `document.hidden` check is new. | Messenger |
| 12 | Reconnecting socket client | `frontend/src/services/ws.js` | Low | Not reused | Tara's `lib/ws.ts` is already better: fresh-token check, pong timeout, `_reconnected` refetch. | — |

### 8.2 Social and profiles

| # | Feature | QTech files | Value | Verdict | What to take, and corrections | Tara target |
|---|---|---|---|---|---|---|
| 13 | Two-level comment threads | `backend/social/models.py` (`Comment`), `views.py` (`CommentViewSet.perform_create`), `frontend/src/components/social/CommentList.vue` | Medium | Overstated | Tara's `CommentList.vue` already shows "replied to X". Port only the server rule: `parent` is the thread root, `reply_to` is the answered comment, and both authors are notified. QTech's writable `parent`, its N+1 replies, and its mention link that passes a comment id as a user id must not be copied. | Social (post service) |
| 14 | Photo theater and media grid | `frontend/src/components/social/PostFeed.vue` (lines 209-266, 363-383) | High | Confirmed for social and profiles; Overstated for marketplace | Take the 1/2/3/4+ grid with a "+N" overlay, the viewer state in the URL so Back closes it, swipe, arrows and Escape, and the thumbnail strip. `?view=` holds only the post id, so a refresh reopens at image 0. Swipe and arrows are not RTL-aware. No focus trap. `PhotoViewer.vue` is a separate single-image viewer. Tara's listing page already has its own gallery. | Social, profiles, video |
| 15 | Events and RSVP | `backend/social/models.py` (`Event`, `EventAttendance`), `views.py` (`EventViewSet`), `frontend/src/pages/app/modules/SocialEvents.vue` | Medium | Overstated | Only the model shape and the upcoming/past tabs carry over. `is_public` is never enforced, the status is not validated, and the attendees list is unpaginated and open to all staff. | Social |
| 16 | Who-reacted list, reaction summary, gesture handling | `backend/social/views.py` (`PostViewSet.reactions`), `PostFeed.vue` | Low | Overstated | Tara's `PostActions.vue` already has hover, long-press and `suppressClick`. QTech's breakdown is N+1 per post. Only the idea of a who-reacted endpoint remains. | Social |
| 17 | Profile photo as a post | `backend/social/models.py` (`Post.photo_kind`), `views.py` (`profile_photo`) | Medium | Confirmed (idea only) | Avatar and cover changes become reactable posts hidden from the timeline. QTech implements this as a GET that writes rows and accepts any `user_id`, so rebuild it with events. | Profiles, social |
| 18 | One visibility resolver plus a test matrix | `backend/tasks/visibility.py`, `backend/tasks/tests.py`; the IDOR in `backend/social/views.py` | Medium | Overstated | The IDOR lesson is real. The "consistency" test is tautological, and Tara's graph-based audience check cannot be written as one queryset. Only the test-matrix idea transfers. | All content services |
| 19 | Relationship flags computed once per page | `backend/social/views.py`, `serializers.py` | Low | Overstated | The same serializer still runs per-row COUNTs, so only the idea transfers. | Graph |

### 8.3 Media, images and uploads

| # | Feature | QTech files | Value | Verdict | What to take, and corrections | Tara target |
|---|---|---|---|---|---|---|
| 20 | HEIC to JPEG before upload | `frontend/src/utils/heic.js` | Medium | Confirmed, with caveats | 19 lines with a lazy `heic2any` import. iOS Safari already converts HEIC for `accept="image/*"`, so the gain is mainly on desktop and Android. `heic2any` 0.0.4 is unmaintained, about 1.35 MB, decodes on the main thread and bundles libheif (LGPL; check the licence). Exclude it from Tara's service-worker precache. | Media upload pickers |
| 21 | Image rendition safety rules | `backend/core/images.py` | Medium for video posters; Low for avatars | Confirmed for posters; Overstated for avatars | Take the width ladder, no upscaling, EXIF transpose, pixel cap and atomic write. QTech skips a rung equal to the source width (`w <= width`; port as `w < width`) and checks size before rotating. Tara's thumbnail task already transposes and never upscales. The 50 MP cap is too high for a 256 MB worker. | Media, video |
| 22 | Responsive image / LCP contract | `frontend/src/components/ui/SmartImage.vue` | Medium | Confirmed | One priority image (eager, high fetch priority), every other image lazy, explicit width and height. The URL builder in `utils/media.js` is QTech-specific; Tara builds `srcset` from its own variants. | Video, reels, feed |
| 23 | Upload hardening at the edge | `nginx/nginx.conf` (`location /media/`) | Low | Overstated | A sandbox CSP and `nosniff` on uploads are right. But Tara's `/tara-media/` already inherits the server-level headers; adding `add_header` there would drop all of them unless every one is re-declared. | Edge |

### 8.4 Marketplace, CMS and shared utilities

| # | Feature | QTech files | Value | Verdict | What to take, and corrections | Tara target |
|---|---|---|---|---|---|---|
| 24 | Price semantics and effective-price ordering | `backend/cms/models.py` (`Product`, `Currency`), `serializers.py`, `views.py` (`ProductViewSet`) | High | Confirmed | `null` means price on request, `0` means free, `sale_price` is cleared when there is no price, and sorting uses `Coalesce(sale_price, price)` with unpriced items last. QTech never enforces `sale_price < price`. | Marketplace |
| 25 | Facet counts | `backend/cms/views.py` (`ProductViewSet.facets`) | Low | Overstated | One dimension only; the counts include the active filter, so chips collapse to one value once selected; no cache. Only the principle transfers. | Marketplace |
| 26 | Tolerant category filter | `backend/cms/views.py` (`CategoryTolerantFilter`) | Low | Overstated | One line of code. Only the rule transfers: an unknown category gives an empty result, not a 400. | Marketplace |
| 27 | Schema-driven settings and attribute catalogue | `backend/cms/chrome.py`, `frontend/src/pages/app/modules/CmsChromeForm.vue` | Medium | Overstated | A catalogue owned by the server and served to the UI is a good pattern. But there is no number kind, unknown keys are silently dropped, there are no length caps or URL checks, and the labels are hard-coded Arabic. | Marketplace attributes, admin settings |
| 28 | Price display and money formatting | `frontend/src/components/ui/PriceTag.vue`, `frontend/src/utils/money.js` | Medium | Overstated | The three-state price display is reusable. `formatMoney` rounds three-decimal currencies to two decimals: 12.125 KWD shows as 12.13. | Marketplace |
| 29 | Filter chip and sort sheet | `frontend/src/components/ui/FilterChip.vue`, `SortSheet.vue` | Medium | Confirmed | Fix while porting: hard-coded Arabic, `aria-haspopup="listbox"` on a dialog, and no focus trap. | Marketplace |
| 30 | Crawler link previews (OG, JSON-LD) | `frontend/nginx.conf` (crawler map, internal `/__social/`), `backend/cms/social.py` | High | Confirmed | Take the UA map and internal rewrite; human visitors always get the SPA. Do not copy: JSON-LD written without escaping `<` (a user title can break out of `<script>`); `og:url` and canonical built from the internal path; `throttle_classes = []`; any `og:image` placed under the internal location, where crawlers cannot fetch it. The Pinterest entry also matches Pinterest's in-app browser. | Social, marketplace, video, profiles |
| 31 | Arabic text normalization | `backend/core/chatbot.py` (`_norm`, `_tokens`) | High for search | Confirmed for search and trending; Overstated as a uniqueness key or moderation filter | Folds alef, ya, ta-marbuta and hamza forms, and strips diacritics and tatweel. Missing: NFKC, Arabic-Indic digits, Persian ی and ک, and handling of the definite article "ال". Replacing every symbol merges "C", "C#" and "C++". Zero-width characters defeat it. | Search, trending, skills, moderation |
| 32 | Versioned-namespace cache | `backend/core/cache.py` | Medium | Confirmed, with a defect | Bump a version counter to invalidate a whole namespace. Fix the key typo, the get-then-set race and the ignored `ttl`. Also fix `bump_version` resetting to 1 after eviction, which brings stale v1 entries back; start versions at a value that never repeats. | Shared library |
| 33 | Draft, publish and revision workflow | `backend/cms/models.py` (`Page`, `PageRevision`), `views.py` (`PageViewSet`) | Medium | Confirmed (concept) | Snapshot before overwrite, restore into the draft, and an undoable discard. QTech's publish has no `transaction.atomic`. | Ad creative revisions, pages |
| 34 | Block page builder and validator | `backend/cms/blocks.py`, `backend/cms/models.py` (`Page`), `AdminPages.vue`, `BlockRenderer.vue`, `backend/cms/tests_pages.py` | High | Not re-verified | A block catalogue owned by the server, a strict envelope, a depth cap and sanitize-on-write, backed by QTech's best tests. Image and URL props are unvalidated strings (`javascript:` risk). | Business pages, storefronts |
| 35 | HTML allowlist sanitizer and XSS tests | `backend/cms/sanitize.py`, `backend/core/sanitize.py`, `tests_pages.py` (`SanitizerTests`) | High | Not re-verified | Reuse the XSS test cases. Merge the two diverging sanitizers into one, and consider nh3. | Shared library |
| 36 | CSV export with BOM | `backend/core/export.py` | Low | Confirmed | Add formula-injection escaping and a safe `Content-Disposition` filename. | Admin and ads exports |
| 37 | Invoice numbering lesson | `backend/billing/models.py` (`Invoice`) | Low | Confirmed as a lesson; the statement shape itself is Overstated | Do not derive a number in an UPDATE after insert on a unique blank column. Quantize to each currency's minor unit, not 0.01. | Marketplace orders, ads statements |

### 8.5 Analytics, ads and geolocation

| # | Feature | QTech files | Value | Verdict | What to take, and corrections | Tara target |
|---|---|---|---|---|---|---|
| 38 | Visibility clock (dwell, watch time, ad viewability) | `frontend/src/composables/useVisitorTracking.js`, `backend/core/tracking.py` | High | Confirmed | Time counts only while the tab is visible. Flush on `visibilitychange`, use `pagehide` rather than `unload`, and send a JSON Blob so DRF accepts it. The clock is per page, with no IntersectionObserver, so element viewability is new code. The server-side clamps are good; the Postgres writes on every beacon (about 7 queries) are not. | Ads, video, reels |
| 39 | Traffic attribution and bot filter | `backend/core/attribution.py` | Medium | Confirmed for inbound traffic; Overstated for ads | A pure, easily tested function. Outbound UTM tagging for ads is new code. `is_bot()` adds little when every API requires login. | Ads, analytics |
| 40 | GeoIP country lookup | `backend/core/geo.py`, `backend/core/tasks.py`, `backend/core/management/commands/update_geoip.py` | High | Confirmed | Take the reader that reopens on file mtime under a lock, and the single-flight refresh. The atomic download, validate and swap step lives in `update_geoip.py`. `lookup()` returns empty for private IPs before it reads the Cloudflare header, so reorder those checks. QTech uses City Lite; Tara needs only Country Lite (CC-BY attribution). | Ads targeting |
| 41 | Session analytics metric definitions | `backend/core/session_analytics.py`, `analytics.py` | Low | Overstated | Bounce means one page, engaged time is summed visible dwell, and bots are excluded but counted. Request-time aggregation and raw IPs do not transfer. | Video and ads analytics |
| 42 | Device class from the user agent | `backend/core/useragent.py` | Low | Overstated | No "tv" class. Android tablets are classified as mobile and iPadOS as desktop. | Analytics |
| 43 | Deduplicated view counting | `backend/core/visitors.py`, `backend/core/models.py` (`PageHit`) | Low | Overstated | Only the `SET NX EX` cooldown idea; QTech writes the database on every hit. | Marketplace, video |
| 44 | Single-flight Celery lock | `backend/core/tasks.py` (`refresh_geoip`) | Low | Confirmed | Releasing the lock must check ownership; QTech deletes it unconditionally. | Any long job |

### 8.6 Professional (recruitment)

| # | Feature | QTech files | Value | Verdict | What to take, and corrections | Tara target |
|---|---|---|---|---|---|---|
| 45 | ATS data model | `backend/hr/models.py` (`JobOpening`, `Candidate`, `JobApplication`, `Interview`, `InterviewFeedback`, `Offer`) | High | Confirmed | The 8-value stage enum, unique (job, candidate), the interview panel, one scorecard per panelist, and the 1:1 offer. Rating has no range constraint. `panelist` is `SET_NULL`, which breaks the unique constraint once a panelist is deleted. | Professional |
| 46 | Stage action, panelist scoping, pipeline counts | `backend/hr/views.py`, `backend/hr/dashboard.py` | Medium | Overstated | Stage can also be changed through PATCH, and QTech's own UI does so. The stage action allows any move between stages. The pipeline aggregate is global, not scoped. | Professional |
| 47 | Public careers board and apply | `backend/hr/careers.py`, `frontend/src/pages/public/CareersPage.vue` | Medium | Overstated | Open-only lists and an "already applied" response. It is not truly idempotent (no race handling), anyone can overwrite a candidate by email, the throttle scope is shared with sign-up, and the modal is not accessible. | Professional |
| 48 | Recruiter pipeline Kanban | `frontend/src/pages/app/modules/HrRecruitment.vue`, `TasksBoard.vue` | Medium | Confirmed (layout reference) | Responsive stage columns and optimistic moves with rollback. `HrRecruitment.vue` has no drag-and-drop, its stage list omits "withdrawn", and it loads 200 applications at once. | Professional |
| 49 | Field-level stripping and write-locking | `backend/hr/serializers.py` | Medium | Confirmed | Remove sensitive fields according to the viewer's capability, and make privileged fields read-only. The capability checks run once per row (N+1). | Profiles, professional |
| 50 | Role-to-capability map | `backend/hr/permissions.py` | Low | Overstated | Based on a global role with no tenant or page scope; only the idea transfers. | Professional, admin |
| 51 | Per-entity activity log | `backend/tasks/models.py` (`TaskActivityLog`) | Low | Confirmed | Fields are actor, action, old and new value, metadata, with an index on (object, -created_at). | Professional, marketplace |
| 52 | Scheduled reminders with "sent" flags | `backend/tasks/tasks.py`, `backend/hr/tasks.py` | Low | Confirmed | Not safe under concurrency; use `skip_locked`. | Notifications |
| 53 | Multi-step approval engine | `backend/hr/approvals.py` | Low | Overstated | Tied to HR models and user flags; use as a design reference only. | Ads review |

### 8.7 Admin, accounts and security

| # | Feature | QTech files | Value | Verdict | What to take, and corrections | Tara target |
|---|---|---|---|---|---|---|
| 54 | Layered staff permissions and matrix editor | `backend/access/services.py`, `permissions.py`, `models.py`, `frontend/src/pages/app/modules/AdminPermissions.vue` | High | Confirmed | Port the precedence algorithm and the matrix UI rules: edit implies view, removing view clears edit, group toggles, and a sticky first column that works in RTL. Do not port the data model. QTech neither validates keys nor audits changes. | Admin |
| 55 | Account lifecycle and hierarchy guard | `backend/accounts/views.py` (`UserViewSet`), `frontend/src/pages/app/modules/AdminUsers.vue` | Medium | Overstated | It lets you act on your own account; suspend only flips `is_active`; most actions are audited after save; and the "typed confirmation" is `window.prompt()`. Only the guard idea transfers. | Admin |
| 56 | Audit trail shape and read API | `backend/core/models.py`, `backend/core/audit.py`, `backend/access/views.py`, `AdminAudit.vue` | Medium | Confirmed | Four composite indexes, plus `target_type` and `target_id`. Category is free text, pagination is by page number, and `record()` stores the raw IP and swallows errors. | Admin |
| 57 | Failed-login security panel | `backend/access/views.py` (`MonitorView`) | Low | Overstated | It groups by a description string that contains the email, and the health pings run one after another. Only the concept transfers. | Admin |
| 58 | Admin monitor polling UX | `frontend/src/pages/app/modules/AdminMonitor.vue` | Medium | Confirmed | Poll every 15 s, skip while the tab is hidden, mount tabs on first open and keep them alive. | Admin |
| 59 | Default manager that hides soft-deleted rows | `backend/accounts/managers.py`, `backend/accounts/models.py`, `backend/core/models.py` | Medium | Confirmed | Point both `default_manager_name` and `base_manager_name` at the all-rows manager. | Profiles, video |
| 60 | Per-account login throttle | `backend/core/throttling.py` (`LoginTargetThrottle`) | High | Not re-verified | Key it on the normalized email. Tara's identity service only throttles per IP. | Identity |
| 61 | Google sign-in claim checks and account linking | `backend/accounts/views.py` (`GoogleLoginView`, `LinkGoogleView`), `GoogleLinkCard.vue` | High | Not re-verified | Take the claim checks and the takeover guard. Verify tokens locally against Google's JWKS, and key linked identities on `sub`. | Identity |
| 62 | Telegram phone verification | `backend/accounts/telegram.py`, `management/commands/set_telegram_webhook.py` | Medium | Not re-verified | A free proof of phone ownership for sellers and professionals. | Identity, marketplace |
| 63 | CSP violation collector | `backend/core/csp.py` | Medium | Not re-verified | Small. Tara's CSP has no report endpoint. | Edge, BFF |
| 64 | Deploy-time checks and env helpers | `backend/core/checks.py`, `backend/qtech_config/settings.py` (`_env`), `backend/entrypoint.sh` | Medium | Not re-verified | Treat empty compose variables as unset, run `check --deploy` before migrate, and migrate only in the web role. | Platform |

### 8.8 Notifications and mobile PWA

| # | Feature | QTech files | Value | Verdict | What to take, and corrections | Tara target |
|---|---|---|---|---|---|---|
| 65 | Push subscription lifecycle | `frontend/src/mobile/push.js` | High | Confirmed | Ask for permission only from a tap, re-attach silently on boot when permission is already granted, and unsubscribe locally first. QTech has no logout hook either. | Notifications |
| 66 | Live notification list and deep links | `frontend/src/composables/useNotifications.js` | Medium | Confirmed | Upsert by id, live socket handlers, and a URL builder per notification type. Updated items are not moved to the top, and unread is counted from the loaded items only. | Notifications |
| 67 | Inline notification actions and mute popover | `frontend/src/components/social/NotificationBell.vue` | Medium | Confirmed | The "actioned" state lives only on the client. Tara's notification item root is a `<button>`, so the layout has to change. | Notifications |
| 68 | Category-prefix muting | `backend/notifications/services.py` | Low | Overstated | Tara's notification kinds share no prefixes with their categories. QTech's mute only gates the WebSocket toast. | Notifications |
| 69 | Service-worker urgent and RTL options | `frontend/public/sw.js` | Low | Overstated | `dir` and `lang` are hard-coded, and a click navigates without a same-origin check. | Notifications |
| 70 | Synthesized notification ping | `frontend/src/utils/sound.js` | Low | Confirmed | Web Audio with no asset file, unlocked on the first gesture, throttled. | Notifications |
| 71 | Offline-only email rule | `backend/chat/tasks.py` | Low | Confirmed (rule only) | QTech's implementation puts every recipient in a single `To:` header. | Notifications |
| 72 | Pull-to-refresh | `frontend/src/mobile/components/PullToRefresh.vue` | Medium | Confirmed | Uses `window.scrollY` and QTech's CSS tokens; adapt it to a scrolling container. | Feed, reels |
| 73 | RTL-aware swipe maths | `frontend/src/mobile/composables/useSwipeBack.js` | Medium | Confirmed for the maths; Overstated as the basis for a story viewer | It is an edge-only back gesture on `#app`; only the constants and the direction flip carry over. | Reels, mobile |
| 74 | URL-backed overlays | `PostFeed.vue` (`openViewer`, `closeViewer`) | Medium | Confirmed | Back closes sheets, and deep links reopen them. | Reels, profiles, messenger |
| 75 | Mobile PWA shell pieces (update handshake, kept-alive tabs, idle prefetch) | `frontend/src/mobile/App.vue`, `components/UpdateBar.vue`, `router.js` | Medium | Not re-verified | Do not take `InstallGate` or the authenticated API cache in `app-sw.js`. | Frontend |
| 76 | Theme contrast maths | `frontend/src/stores/theme.js` | Low | Not re-verified | `contrast`, `forDarkSurface` and `scrimFor`, for accent colours chosen by users. | Pages, storefronts |

### 8.9 Do not copy

These choices appear in QTech but must not reach Tara:
- HS256 user tokens signed with `SECRET_KEY`.
- Tokens in `localStorage`, or in WebSocket query strings, without an exit plan.
- Client-chosen LiveKit room names. A `call.*` relay to arbitrary user ids. Static TURN credentials in the bundle.
- Presence broadcast to all users, and an "all online ids" endpoint.
- Private files under public `/media/`. Extension-only upload validation. Same-origin SVG or HTML uploads. Inline responses that use the client's Content-Type.
- Synchronous fan-out inside requests, and side effects that swallow every exception.
- Committed secret defaults (VAPID keys) and insecure fallbacks for `SECRET_KEY`, `DEBUG` and `ALLOWED_HOSTS`.
- "Staff or read-only" permission gates on private data. `exclude=` serializers on public endpoints.
- Get-or-create for DMs, applications and similar records without a unique constraint and race handling.
- A purge that is open to every staff member. Admin reset links handed to staff.
- A service-worker cache of authenticated API responses.

---

## 9. Corrections from the verification pass

The verification pass changed or sharpened these audit claims. The corrected version is used throughout this document.

1. **Attribution order** (`backend/core/attribution.py`): the android-app scheme is checked *before* the referrer host match, not after it. Internal referrers are relabelled direct in `tracking.py`, not inside `resolve()`.
2. **Tracking cost** (`backend/core/tracking.py`): one beacon costs about 7 queries, not the 2–3 the audit stated. QTech sends with `sendBeacon` and `credentials:'omit'`, and the clock is per page, not per element.
3. **GeoIP**: the atomic temp-file and `os.replace` swap, plus MMDB validation, live in `backend/core/management/commands/update_geoip.py`, not in `core/tasks.py`. `lookup()` short-circuits private IPs before it reads the Cloudflare header. QTech uses City Lite stored under `MEDIA_ROOT`.
4. **Renditions** (`backend/core/images.py`): the no-upscale check (`w <= width`) also skips a rung equal to the source width, and it runs before EXIF rotation.
5. **Versioned cache** (`backend/core/cache.py`): besides the typo, the race and the ignored `ttl`, `bump_version()` resets to 1 when the key is missing, which can bring stale entries back.
6. **Celery lock** (`backend/core/tasks.py`): the lock is released with an unconditional delete, with no owner token.
7. **UA parser** (`backend/core/useragent.py`): there is no "tv" class, Android tablets come out as mobile, and iPadOS comes out as desktop.
8. **Presence** (`backend/core/realtime.py`): the connection-count hash has no TTL, so counts drift after a gateway crash (only the sorted set's TTL saves presence). Ids are `int()`-cast.
9. **Photo viewer** (`PostFeed.vue`): `?view=` holds only the post id, and the image index resets to 0 on refresh. `PhotoViewer.vue` is a separate single-image viewer, not the theater. Dates are sliced ISO strings, not `ar-EG` formatted.
10. **Comment threads** (`backend/social/serializers.py`, `CommentList.vue`): `parent` and `post` stay writable with no same-post check; replies are N+1; the mention link passes a comment id as a user id. Tara's `CommentList.vue` already shows the "replied to" label.
11. **Events** (`backend/social/views.py`): `attendees()` is unpaginated, runs 3 queries and lists every attendee to any staff member. The upcoming/past split happens on the client.
12. **Recruitment stage** (`backend/hr/serializers.py`, `HrRecruitment.vue`): `stage` is writable through PATCH, and QTech's own UI changes it that way. The stage action allows any move between stages. The pipeline aggregate in `dashboard.py` is global.
13. **ATS model** (`backend/hr/models.py`): `InterviewFeedback.rating` has no range constraint, and `panelist` is `SET_NULL`, which breaks its unique constraint.
14. **Careers apply** (`backend/hr/careers.py`): the throttle scope `register` is shared with sign-up. The 200/201 split is not real idempotency.
15. **Settings catalogue** (`backend/cms/chrome.py`): it has no number kind; unknown keys are silently dropped; there are no length caps and no URL validation.
16. **Facets** (`backend/cms/views.py`): there is a single dimension, and the counts include the active filter.
17. **Money formatting** (`frontend/src/utils/money.js`): fractional amounts in three-decimal currencies are rounded to two decimals.
18. **Crawler previews** (`backend/cms/social.py`): the JSON-LD is not escaped for `<`, `og:url` and canonical are built from the internal path, and the view sets `throttle_classes = []`.
19. **Account lifecycle** (`backend/accounts/views.py`): `get_object()` lets staff act on their own account. Suspend only sets `is_active`. Only purge writes its audit row before acting.
20. **Failed-login panel** (`backend/access/views.py`): it groups by an email-bearing description string, not by account id.
21. **Notifications** (`backend/notifications/services.py`, `useNotifications.js`, `sw.js`): mute gates only the WebSocket toast; upsert does not move updated items to the top; unread is counted from loaded items only; `sw.js` hard-codes `dir` and `lang` and navigates without a same-origin check.
22. **Call UI** (`CallPicker.vue`, `sw.js`): `CallPicker.vue` searches the staff directory. The service worker uses one static tag, `qtech-call`.
23. **HEIC** (`frontend/src/utils/heic.js`): `heic2any` 0.0.4 is about 1.35 MB, unmaintained, and bundles LGPL libheif. iOS Safari already converts HEIC for image pickers.
24. **Arabic normalization** (`backend/core/chatbot.py`): the diacritics range was checked and is correct. It is unsafe as a uniqueness key ("C", "C#" and "C++" merge) and easy to evade in moderation (no NFKC or zero-width stripping, no Persian letters).
25. **Tara's media edge** (from the same pass): Tara's `location /tara-media/` already inherits the server-level security headers. Adding `add_header` inside it would drop them.

---

## Appendix: third-party dependencies

| Group | Packages and versions (from QTech requirements and `package.json`) |
|---|---|
| Django core | Django 4.2.30, djangorestframework 3.17.1, djangorestframework-simplejwt 5.5.1 (token_blacklist), django-filter 25.1, drf-yasg 1.21.15, django-cors-headers 4.9.0, django-jazzmin 3.0.1, whitenoise 6.12.0, python-decouple 3.8 |
| Realtime | channels 4.3.2, channels-redis 4.3.0, daphne 4.2.1 |
| Background | celery 5.6.2, django-celery-beat 2.9.0, kombu 5.6.2, redis 7.1.0, django-redis 5.4.0 |
| Data and media | psycopg[binary] 3.3.2, Postgres 17-alpine, Pillow 12.1.0, django-storages 1.14.6 (installed, unused), maxminddb 3.1.1 with DB-IP City Lite (CC-BY 4.0) |
| Other backend | pywebpush 2.0.3, py-vapid 1.9.4, beautifulsoup4 4.14.3, PyJWT (transitive, but imported directly for LiveKit tokens), pandas 3.0.0, numpy 2.4.2, deep-translator 1.11.4. Dev tools shipped in `requirements.txt`: django-debug-toolbar 6.2.0, ruff 0.4.10. gunicorn 23 is installed but unused |
| Calls | livekit/livekit-server v1.8 (Docker), livekit-client ^2.7.0 |
| Frontend | vue ^3.5, vue-router ^4.5, pinia ^2.2, vue-i18n ^10, axios ^1.7, tailwindcss ^3.4, vite ^6, chart.js ^4.5 + vue-chartjs ^5.3, heic2any ^0.0.4, swiper ^11, lenis ^1.3, vuedraggable ^4.1, topojson-client ^3.1 + world-atlas ^2.0, qrcode-generator ^2.0, lucide-vue-next ^0.460; devDependencies playwright ^1.61 (screenshot script only), axe-core ^4.13 (unused) |
| Images | nginx 1.27-alpine, node:20-alpine, redis:7-alpine, postgres:17-alpine, python:3.11.3-alpine, dpage/pgadmin4 (tools profile) |
| External services | Google STUN, Dokploy + Traefik + Let's Encrypt, Cloudflare (DNS, proxy, `CF-IPCountry`/`CF-Connecting-IP` headers), SMTP, Google Identity Services, Telegram Bot API, an OpenAI-compatible chat API, Google Tag Manager/Analytics, Google Fonts, Office Online viewer |
