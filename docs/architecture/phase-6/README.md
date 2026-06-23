# Phase 6 — Notifications, Search, Moderation, Admin (Report)

> Status: **implemented**. Adds four services that complete the platform's
> cross-cutting backbone — **Notification**, **Search**, **Moderation**,
> **Admin** — plus **RBAC** (roles in the access token) in the shared kernel.

---

## 1. Architecture changes

- **RBAC** added to the shared kernel: `TokenUser.roles` (from the token's
  `roles` claim) + `IsModerator`/`IsAdmin` permission classes. Services enforce
  roles locally; Admin owns the role registry and (future) Identity embeds roles
  at token issuance — Admin already exposes an internal `roles/{id}` endpoint for
  that wiring.
- **Notification**: consumes ~8 domain events (reactions, comments, replies,
  friend requests/accepts, follows, messages, listing status) → in-app
  notifications, respecting per-kind preferences, and emits `notification.created`
  (the Realtime gateway already pushes it to sockets). This is the widest
  fan-in in the system.
- **Search**: Postgres `search_document` is the source of truth **and** the
  fallback; OpenSearch is an optional accelerator. Indexer consumes
  profile/page/post/listing events; queries fall back to Postgres ILIKE if
  OpenSearch is down (`degraded` flag) — graceful degradation per the brief.
- **Moderation**: `*.reported` events (+ a manual report endpoint) open/append
  to one case per target; moderator actions emit `moderation.actioned` (which
  Marketplace/Post already consume to enforce), with an appeal workflow + audit.
- **Admin**: feature flags (read-open / write-admin), role grant/revoke,
  config, and a **service-health overview** that polls every service's
  `/readyz` behind per-service circuit breakers (one slow service can't block
  the page).

## 2. Files created / changed

**Shared kernel:** `tara_common/permissions.py` (new) + `auth.py` (TokenUser.roles).

**Four services** (`services/{notification,search,moderation,admin}/`): each a
full Django service (config, app with models/services/views/urls + events/
handlers where applicable, packaging, tests). Notification & Moderation add
`consume_events` + relay; Search adds an indexer consumer; Admin is web-only with
an internal roles endpoint.

**Infra:** `postgres/init` (+notif/search/moderation/admin DBs), `compose`
(+ services, relays, consumers, optional `opensearch` under the `search`
profile), Traefik routes, `prometheus.yml` (+4 targets), `.env.example`.

## 3. Services added / changed

| Service | Role | Port | Notes |
|---------|------|------|-------|
| **notification** + relay + consumer | in-app notifications | 8008 | fan-in of ~8 events; emits `notification.created` |
| **search** + indexer | search + autocomplete | 8009 | Postgres source-of-truth + OpenSearch optional; degrade flag |
| **moderation** + relay + consumer | reports → cases → actions | 8011 | RBAC (moderator); emits `moderation.actioned` |
| **admin** | flags, roles, health | 8012 | RBAC (admin); internal roles endpoint |
| opensearch | optional index (profile `search`) | 9200 | off by default |

## 4. Database changes

- **`notif_db`**: `notification`, `notification_preference`, `push_device_token`,
  `notification_delivery_log` + outbox/processed.
- **`search_db`**: `search_document` (unique doc_type+doc_id) + processed.
- **`moderation_db`**: `report`, `moderation_case` (**one open case per target**
  via partial unique constraint), `moderation_action`, `appeal`,
  `content_policy`, `moderation_audit_log` + outbox/processed.
- **`admin_db`**: `feature_flag`, `system_config`, `account_role`
  (unique account+role), `audit_log`, `service_health_snapshot`.

## 5. API endpoints (live)

**Notification:** `GET notifications`, `GET notifications/unread-count`,
`POST notifications/read`, `GET/PATCH notifications/preferences`,
`POST devices/push-token`.
**Search:** `GET search?type=&q=`, `GET search/autocomplete?q=`.
**Moderation:** `GET moderation/reports`, `POST moderation/reports/file`,
`GET moderation/cases`, `POST moderation/cases/{id}/{assign,action}`,
`POST moderation/cases/{id}/appeals`, `POST moderation/appeals/{id}/resolve`.
**Admin:** `GET/PATCH admin/feature-flags[/{key}]`, `POST/DELETE admin/roles`,
`GET admin/roles/{id}`, `GET admin/service-health`; internal `roles/{id}`.

## 6. Event contracts

**Published:** `notification.created` (Notification); `moderation.actioned`,
`appeal.created` (Moderation). **Consumed:** Notification — post.reacted/
commented, comment.replied, friendship.requested/accepted, user.followed,
message.created, listing.status.changed; Search — profile.updated, page.created,
post.created/deleted, listing.created/status.changed; Moderation — post.reported,
listing.reported, message.reported.

## 7. Tests

- **Notification:** event→notification creation + emit; no self-notification;
  list/unread-count/mark-read; only-own visibility; push-token; **preference
  mute suppresses**.
- **Search:** profile/post indexed (private post NOT indexed); listing
  de-indexed when not active; query + `degraded=false`; autocomplete prefix.
- **Moderation:** reported event opens **one** case + counts; **RBAC** (queue
  403 for non-moderator, 200 for moderator); action resolves case + emits
  `moderation.actioned`; appeal flow (overturn → approve action); manual report.
- **Admin:** flag read-open/write-admin (403 vs 200); role grant/revoke +
  registry; non-admin blocked; internal roles requires internal token.
- **Quality gates:** `ruff` clean (287 files); `docker compose config` valid.

## 8. Commands

```bash
make up                         # builds the 4 services (+consumers/relays)
make up SEARCH_USE_OPENSEARCH=true   # + docker compose --profile search up opensearch
# direct dev: notification :8008  search :8009  moderation :8011  admin :8012
```

## 9. Risks

| Risk | Mitigation |
|------|------------|
| Notification fan-in volume (message events especially) | Per-kind preferences; in-app only by default; push/email batching later. |
| RBAC depends on roles in the token, which Identity doesn't embed yet | Admin owns the registry + internal endpoint; Identity integration is a documented follow-up. Until then roles are set by the issuer/tests. |
| Search DB ILIKE won't scale | OpenSearch accelerator behind a flag; Postgres stays the fallback + source of truth (rebuildable by event replay). |
| `moderation.actioned` enforcement depends on each owner consuming it | Already wired in Marketplace; Post consumes block/moderation similarly — add per content type as needed. |
| AI moderation | **Interface only** — never the sole decider (brief §M); not built. |

## 10. Rollback notes

- Additive: 4 DBs + 4 services (+ consumers/relays) + optional OpenSearch + a
  shared-kernel permissions module. Rollback = revert the Phase-6 commit / drop
  the four `services/*` dirs + compose blocks; `tara_common.permissions` and
  `TokenUser.roles` are inert if unused. Earlier services untouched.
- Each DB is independent; `make clean` wipes dev volumes.

## 11. Completion checklist

- [x] RBAC: token roles + `IsModerator`/`IsAdmin`
- [x] Notification: multi-event fan-in, preferences, push tokens, read state, emit
- [x] Search: index sync via events, query + autocomplete, OpenSearch-optional + DB fallback
- [x] Moderation: report intake → single case per target → actions → `moderation.actioned`, appeals, audit, RBAC
- [x] Admin: feature flags, role registry (+internal endpoint), service-health overview, RBAC
- [x] Infra: 4 DBs, compose services, Traefik routes, Prometheus, optional OpenSearch profile
- [x] `ruff` clean (287 files); `docker compose config` valid
- [x] **Verified: Notification 6/6, Search 4/4, Moderation 5/5, Admin 4/4 green
      against PostgreSQL**; `ruff` clean (287 files); `docker compose config` valid.
- [ ] **Your approval to proceed to Phase 7 — Advertisement.** ← gate

### Verification notes

Run on the host venv against Dockerized Postgres (in-container image build
blocked only by the sandbox corporate-CA TLS limit; CI builds images). No
service-code bugs; only a test-fixture password mismatch for the `adminsvc` DB
role was corrected in the runner.
