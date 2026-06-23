# Phase 8 — Web Frontend (Report)

> Status: **implemented & verified**. Delivers the **Tara web client** — a
> Vue 3 + TypeScript SPA that consumes the existing microservices through the
> edge gateway, with **Arabic RTL / English LTR**, **dark/light/system** themes,
> realtime chat & notifications over the Channels gateway, and graceful
> degradation when individual services are unavailable. No new backend code,
> databases, or events were introduced in this phase.

---

## 1. Architecture changes

- New deliverable `frontend/web/` — a **client-only SPA** (Vue 3 `<script setup>`,
  Vite, Pinia, Vue Router, Tailwind, vue-i18n). It is **not** a microservice: it
  ships as static assets and talks **only** to the gateway, never to a service
  directly. This preserves the service boundary — the frontend depends on the
  public `/api/v1/*` contracts and the `/ws/v1/` realtime endpoint, nothing else.
- **Token flow (SPA variant):** access + rotating refresh tokens are held client
  side; a single-flight axios interceptor refreshes on `401` and retries once,
  then drops to the login screen on failure. The mobile-style body-token flow is
  used so the SPA works cross-origin in dev; a production web deployment should
  prefer the httpOnly refresh cookie the identity service already sets (noted as
  a follow-up, **ADR-005**, not yet wired).
- **Realtime:** one `WebSocket` to the Channels gateway authenticated by access
  token, with capped exponential-backoff reconnect and a topic fan-out
  (`message`, `typing`, `notification`, `_status`). Presence/typing/receipts and
  live message/notification frames flow through it; the UI shows an offline
  banner when the socket or the browser goes offline.
- **Degradation everywhere:** every view tolerates a failing dependency —
  profile load failure still lets auth succeed; notification/unread-count
  failures keep the last known value; feed/search/marketplace errors render a
  retryable `ErrorState` rather than crashing the shell.
- **i18n + direction + theme** are applied **before first paint** (in `main.ts`
  via the UI store) so there is no flash of wrong direction/theme; the document
  `dir`/`lang` and the `.dark` class are toggled at the root.

## 2. Files created / changed

**New tree `frontend/web/`** (37 `.vue` + 24 `.ts`):

- **Build/config:** `package.json`, `vite.config.ts`, `tsconfig.json`,
  `tsconfig.node.json`, `env.d.ts`, `tailwind.config.js`, `postcss.config.js`,
  `index.html`, `.env.example`, `.gitignore`.
- **Core (`src/`):** `main.ts`, `App.vue`, `style.css`, `types/index.ts`.
- **Libs (`src/lib/`):** `tokens.ts` (token storage), `api.ts` (axios + refresh
  interceptor + error envelope), `ws.ts` (realtime client), `format.ts`
  (media URL, avatar color/initials, localized relative time).
- **i18n (`src/i18n/`):** `index.ts` (+ `setLocale` direction switch), `en.ts`,
  `ar.ts`.
- **Stores (`src/stores/`):** `auth.ts`, `ui.ts` (theme/locale/online),
  `notifications.ts` (unread badge, live increments).
- **Router:** `src/router/index.ts` (lazy routes + `auth`/`guest`/`staff` guards).
- **Services (`src/services/`):** `profile, graph, post, feed, chat,
  marketplace, notification, search, media, admin`.
- **Components (`src/components/`):** `layout/` (AppShell, SidebarNav, TopHeader,
  MobileNavigation, navItems), `common/` (UserAvatar, ThemeToggle, LocaleToggle),
  `post/` (PostCard, PostComposer, SponsoredCard), `social/` (FollowButton,
  FriendButton), `chat/` (ConversationList, MessageBubble, MessageComposer),
  `marketplace/MarketplaceCard`, `search/SearchBar`,
  `notifications/NotificationItem`, `states/` (LoadingSkeleton, EmptyState,
  ErrorState, OfflineState).
- **Views (`src/views/`):** Landing, Login, Register, Home, Profile, Friends,
  Messages, Marketplace, ListingDetail, Notifications, Search, Settings, Admin,
  NotFound.

No backend files changed.

## 3. Services added / changed

| Component | Role | Port | Notes |
|-----------|------|------|-------|
| **frontend/web** | Vue 3 SPA (static client) | 5173 (dev) | Consumes gateway `/api/v1/*` + `/ws/v1/`; no DB, no events, no server runtime |

No backend services were added or modified.

## 4. Database changes

**None.** The frontend owns no database. Client-side persistence is limited to
`localStorage` keys: `tara.access`, `tara.refresh`, `tara.locale`, `tara.theme`.

## 5. API endpoints (consumed)

The client calls existing gateway contracts only (no new endpoints). Mapped per
service module:

- **auth/identity:** `POST /auth/register`, `/auth/login`, `/auth/refresh`,
  `/auth/logout`, `GET /auth/me`.
- **profile:** `GET /profiles/me`, `GET /profiles/{handle}`, `PATCH /profiles/me`.
- **graph:** follows `POST/DELETE/GET /follows/{id}`; friends
  `POST /friends/requests`, `…/{id}/accept|decline`, `GET /friends`,
  `DELETE /friends/{id}`; blocks `POST/DELETE /blocks/{id}`.
- **post:** `POST/GET/DELETE /posts`, reactions, `…/comments`, `…/shares`, `…/save`.
- **feed:** `GET /feed` (reads `data` + sibling `sponsored` + `page`).
- **chat:** `GET /conversations`, `POST /conversations/dm`, `…/messages`,
  `…/receipts`.
- **marketplace:** `GET/POST /listings`, `GET /listings/{id}`, `…/save`.
- **notification:** `GET /notifications`, `…/unread-count`, `…/read`, `…/read-all`.
- **search:** `GET /search`, `GET /search/suggest`.
- **media:** `POST /media`, `GET /media/{id}`, `…/{id}/raw`.
- **moderation/admin:** `GET /admin/metrics`, `GET/POST /moderation/reports…`.

> Where a client guess at a path/shape is ahead of a confirmed backend route
> (e.g. friend-request direction filters, `media/{id}/raw`), it is isolated in
> the service module so it can be reconciled in one place during integration
> testing.

## 6. Event contracts

**None produced.** The client is a **consumer** of realtime frames pushed by the
Channels gateway. Frame types handled: `message` (live chat), `typing`,
`notification` (unread-badge increment), `_status` (internal socket state).
Outbound frames: `typing`. No domain events are emitted by the frontend.

## 7. Tests / verification

This phase is TypeScript/Vue, so verification is **type-check + production
build**, not pytest:

- `npm install` → **157 packages, exit 0** (required `NODE_OPTIONS=--use-system-ca`
  so Node trusts the Windows cert store behind the corporate TLS proxy — the
  npm analogue of the pip trusted-host workaround).
- `vue-tsc --noEmit` → **0 type errors** under `strict` + `noUnusedLocals` +
  `noUnusedParameters`.
- `vite build` → **1720 modules transformed, built in ~2.5s, exit 0**; all 14
  views emitted as lazy-loaded chunks; main bundle ~221 kB (≈83 kB gzip).

No runtime/E2E tests yet (no test runner wired) — called out in §9.

## 8. Commands

```bash
# from frontend/web/
# Behind the corporate TLS proxy, prefix install with the system-CA flag:
#   PowerShell:  $env:NODE_OPTIONS='--use-system-ca'; npm install
npm install
npm run dev        # Vite dev server on :5173
npm run typecheck  # vue-tsc --noEmit
npm run build      # vue-tsc --noEmit && vite build  → dist/
npm run preview    # serve the built dist/
```

`.env` (copy from `.env.example`): `VITE_API_BASE=http://localhost:8080/api/v1`,
`VITE_WS_URL=ws://localhost:8080/ws/v1/`.

## 9. Risks / limitations (honest)

- **Not yet integration-tested against live services.** The build proves the
  client compiles and type-checks; it has **not** been run end-to-end against the
  running compose stack. Endpoint paths/response shapes inferred from the docs
  may need reconciliation (§5).
- **No frontend test suite** (no Vitest/Playwright). Logic correctness rests on
  the type-checker only.
- **SPA token storage** keeps the refresh token in `localStorage` (XSS-exposed).
  Acceptable for dev; production web should switch to the httpOnly refresh cookie
  (ADR-005) before launch.
- **Media upload** assumes a direct multipart endpoint; production uses presigned
  URLs (media-service design) — the `media.ts` module is the single swap point.
- **Friend relationship state** is derived from `profile.are_friends` only
  (follow state defaults to "not following") because there is no single
  relationship-summary endpoint yet; this can over/under-state a button until a
  dedicated endpoint exists.
- **No mobile app** in this phase — API contracts are mobile-ready, but only the
  web client is built (per the standing scope rule). No PWA/offline cache, no
  push notifications.
- **Not built / placeholder (unchanged from prior phases):** no E2E encryption,
  no real payments/shipping (marketplace shows an explicit "payments & shipping
  not enabled" notice), no mobile apps.

## 10. Rollback notes

- Fully isolated: delete/ignore `frontend/web/` — **zero** backend impact (no
  shared code, migrations, events, or infra). The compose stack is unaffected.
- No gateway routes were added for the SPA in this phase (it is served
  separately in dev via Vite); nothing to revert in `infra/`.
- Client-only state lives in `localStorage` under the `tara.*` keys; clearing
  them fully resets the client.

## 11. Completion checklist

- [x] Vue 3 + TS + Vite + Pinia + Router + Tailwind scaffold
- [x] axios client with JWT attach + single-flight refresh + error envelope
- [x] WebSocket client with backoff reconnect + topic fan-out
- [x] i18n **ar/en** with **RTL/LTR** direction switch + **dark/light/system**
- [x] Auth (login/register/logout/bootstrap) + route guards (auth/guest/staff)
- [x] 10 service modules mapping the gateway contracts
- [x] 22 reusable components incl. loading/empty/error/offline states
- [x] 14 views (landing/auth/home/profile/friends/messages/marketplace/listing/
      notifications/search/settings/admin/404)
- [x] Feed with sponsored-slot blending + graceful degradation
- [x] Realtime chat (typing/live messages/read receipts) + live notification badge
- [x] Marketplace with explicit payments-disabled notice (no fake payments)
- [x] `npm install` ✓ · `vue-tsc --noEmit` ✓ (0 errors) · `vite build` ✓
- [ ] **End-to-end run against the live compose stack** — deferred to integration
- [ ] Frontend test suite (Vitest/Playwright) — deferred

---

### STOP — awaiting approval

Phase 8 (web frontend) is implemented and verified at the build/type-check level.
**Next (Phase 9):** scale, security & production readiness — and, as a bridge,
an **end-to-end integration pass** of this client against the running services
(reconciling any endpoint/shape mismatches from §5/§9). Reply **"كمل"** to proceed.
