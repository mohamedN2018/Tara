# Phase 2 — Profile & Social Graph (Report)

> Status: **implemented**. Adds the **Profile** and **Social Graph**
> microservices, the first **cross-service event flow** (`account.registered`
> fans out to both), the event-bus **consumer framework**, field-level
> **privacy** resolved across services with a circuit-breaker fallback, and the
> **Pages** foundation.

---

## 1. Architecture changes

- Added two independently deployable services (own DB, API, events, pipeline):
  **Profile** (`profile_db`) and **Social Graph** (`graph_db`).
- Extended the shared kernel with an **event consumer framework**
  (`tara_events.dispatch` + `tara_events.worker`): a `@on_event` registry and a
  kombu topic-queue consumer with idempotency + dead-letter handling. This is
  the read side of the outbox→broker backbone built in Phase 1.
- First **cross-service async flow**: Identity's `account.registered` is now
  consumed by **both** Profile (provisions an empty profile) and Graph
  (records an `AccountRef`) — fan-out to multiple independent consumers.
- First **synchronous cross-service read with graceful degradation**: Profile
  resolves `friends_only` visibility by calling Graph's **internal** API behind
  a timeout + circuit breaker; if Graph is down it degrades to "not friends"
  (safest) rather than failing the page load.
- First **internal (service-to-service) APIs**, authenticated by short-lived
  HS256 service tokens and **not exposed at the edge**.

## 2. Files created / changed

**Shared kernel:** `libs/tara_events/tara_events/{dispatch.py,worker.py}` (+
`__init__` exports).

**Profile service** (`services/profile/`): full Django service —
`config/*`, `profiles/{models,services,privacy,clients,events,handlers,
serializers,views,urls,internal_views,internal_urls,admin,apps}.py`,
management `consume_events`, `tests/`, `Dockerfile`, `entrypoint.sh`,
`requirements*.txt`, `pytest.ini`, `conftest.py`, `scripts/wait_for_db.py`.

**Social Graph service** (`services/graph/`): same layout —
`graph/{models,services,events,handlers,serializers,views,urls,
internal_views,internal_urls,apps}.py`, `consume_events`, `tests/`, packaging.

**Infra:** `infra/postgres/init/01-create-databases.sh` (+profile_db, graph_db),
`infra/compose/docker-compose.yml` (+6 services: profile/graph web, relay,
consumer; Traefik routes; tightened Identity route), `infra/observability/
prometheus.yml` (+scrape targets), `.env.example` (+DB creds, JWKS/Graph URLs).

## 3. Services added / changed

| Service | Role | Port (dev) | Notes |
|---------|------|-----------|-------|
| **profile** | profiles + pages API | 8001 | own DB; verifies tokens via JWKS |
| **profile-relay** | Celery worker+beat | — | drains profile outbox |
| **profile-consumer** | event consumer | — | account.registered, user.blocked/unblocked |
| **graph** | friends/follows/blocks API | 8002 | own DB; internal relationship API |
| **graph-relay** | Celery worker+beat | — | drains graph outbox |
| **graph-consumer** | event consumer | — | account.registered, profile.updated |
| identity | (unchanged) | 8000 | Traefik route narrowed to `/auth`,`/me`,… |

## 4. Database changes

- **`profile_db`**: `user_profile`, `profile_field_privacy`, `user_link`,
  `user_education`, `user_work_experience`, `page`, `page_member`,
  `blocked_pair` (read-model) + platform tables (`outbox_event`,
  `processed_event`, `idempotency_record`). Unique handle; unique
  `(profile, field_key)`, `(page, account_id)`, `(blocker, blocked)`.
- **`graph_db`**: `account_ref` (read-model), `friendship`
  (**unique (low,high)** + **CHECK low<high**), `follow_relation`
  (**unique (follower,target,type)**), `block_relation`
  (**unique (blocker,blocked)**), `close_friend_relation` + platform tables.
- Invariants are DB-enforced so idempotent/concurrent actions can't duplicate.
- Same Phase-1 migration approach (generated on first boot in dev; commit before
  staging — see [doc 07](../phase-0/07-migration-and-rollout.md)).

## 5. API endpoints (live)

**Profile** (`/api/v1/`): `GET/PATCH profile/me`, `PUT profile/me/privacy`,
`GET/POST profile/me/{links,education,work}` + `DELETE …/{id}`,
`GET users/{handle}` (privacy-applied), `POST pages`, `GET pages/{handle}`,
`PATCH pages/id/{id}`, `POST pages/id/{id}/members`,
`PATCH pages/id/{id}/members/{member_id}`. Internal: `GET /internal/v1/
profiles/{account_id}/snapshot`.

**Graph** (`/api/v1/`): `POST friends/requests`, `GET friends/requests`,
`POST friends/requests/{id}/{accept,reject}`, `DELETE friends/{user_id}`,
`GET friends`, `POST/DELETE follows/{user_id}`, `GET follows/{followers,
following}`, `POST/DELETE blocks/{user_id}`, `GET blocks`,
`GET social/{user_id}/{friends,followers,mutual}`. Internal:
`GET /internal/v1/relationship?a=&b=`.

> Routing note: relationship lists live under graph-owned prefixes
> (`/social/...`) instead of the brief's illustrative `/users/{id}/friends`, so
> each service owns a clean, non-overlapping path prefix at the gateway.

## 6. Event contracts

**Consumed:** `account.registered` (Profile → create profile; Graph →
AccountRef), `user.blocked`/`user.unblocked` (Profile → block read-model),
`profile.updated` (Graph → refresh cached handle).

**Published (v1):** `profile.updated`, `page.created`, `page.member.changed`
(Profile); `friendship.requested/accepted/removed`, `user.followed/unfollowed`,
`user.blocked/unblocked` (Graph). All via outbox → `tara.events`.

## 7. Tests

- **Profile** (Postgres-backed): event-driven provisioning (idempotent),
  GET/PATCH me + `profile.updated` emitted, **friends_only hidden→visible**
  (Graph mocked), **blocked → 404**, **field privacy hides bio**, page create +
  member permission checks, internal snapshot requires internal token.
- **Graph**: friend request→accept makes friends, duplicate request 409 (single
  symmetric row), can't friend/follow self, unfriend idempotent, follow
  idempotent + unfollow, **block severs follow + prevents re-follow**, block
  prevents friend request, internal relationship requires token + reports flags.
- **Quality gates:** `ruff check` + `ruff format --check` clean across all libs
  + services (112 files). CI path filters already cover new services via the
  `services/**` + `libs/**` patterns (per-service jobs can be added as they grow).

Run: `make test SERVICE=profile`-style (or `cd services/<svc> && pytest`).

## 8. Commands

```bash
make up            # now also builds/starts profile(+relay,+consumer) & graph(+…)
make migrate       # identity; profile & graph auto-migrate on first boot
# direct service access in dev:
#   profile  http://localhost:8001/api/v1/docs/
#   graph    http://localhost:8002/api/v1/docs/
# event consumers run as their own containers (profile-consumer, graph-consumer)
```

## 9. Risks

| Risk | Mitigation |
|------|------------|
| `friends_only` correctness depends on Graph availability | Circuit breaker + safe default (not-friends); local block read-model as backstop. |
| Block read-model in Profile is eventually consistent | Authoritative block flag also comes from the Graph call; either source triggers hide. |
| Cross-service event ordering (profile created before a follow targets it) | Graph doesn't hard-require AccountRef for writes (trusts the id); AccountRef is best-effort for suggestions. |
| More containers (6 added) raise dev/ops footprint | Compose profiles; relay+beat combined per service; consumers are thin. |
| Handle generation collisions | DB unique + retry loop with random suffix. |
| Internal endpoints must never reach the edge | No Traefik labels on `/internal`; reached only over the cluster network; HS256 service-token checked. |

## 10. Rollback notes

- Additive: new services + new DBs + new shared modules. Rollback = revert the
  Phase-2 commit / remove `services/profile`, `services/graph`, and the compose
  blocks; Identity/Phase-1 are untouched except the **narrowed Traefik route**
  (revert that label to restore the prior `/api` catch-all if needed).
- Data: `profile_db` and `graph_db` are independent; dropping them doesn't affect
  `identity_db`. `make clean` wipes all dev volumes.
- Feature-flag/disable: stop `profile-consumer`/`graph-consumer` to pause event
  processing without data loss (events remain queued/outboxed).

## 11. Completion checklist

- [x] Event consumer framework (registry + kombu worker + DLQ + idempotency)
- [x] Profile service: profiles, field-level privacy, links/education/work, Pages + roles
- [x] Profile consumes `account.registered` (provision) + block events
- [x] Profile→Graph sync read for `friends_only` with circuit-breaker fallback
- [x] Social Graph: friends (request/accept/reject/unfriend), follows, blocks
- [x] DB-enforced invariants + idempotency; block severs relationships
- [x] Graph consumes `account.registered` (AccountRef) + `profile.updated`
- [x] Internal service APIs (relationship, profile snapshot) — edge-isolated
- [x] Both services publish domain events via the outbox
- [x] Infra: per-service DBs, compose services, Traefik routes, Prometheus
- [x] `ruff` clean (112 files); `docker compose config` valid
- [x] **Verified: Profile 7/7 and Graph 9/9 green against PostgreSQL**; `ruff`
      clean (112 files); `docker compose config` valid.
- [ ] **Your approval to proceed to Phase 3 — Posts, Feed & Media.** ← gate

### Verification notes

Run on the host venv against a Dockerized Postgres (the in-container image build
is blocked in this sandbox by the same corporate-CA/TLS limitation noted in the
[Phase 1 report](../phase-1/README.md) — not a code issue; CI builds the images).
One real bug was caught and fixed during the run: `follower_ids`/`blocked_ids`
returned `UUID` objects instead of strings (inconsistent with the rest of the
graph API) — now normalized, with regression coverage in
`test_follow_is_idempotent_and_unfollow`.
