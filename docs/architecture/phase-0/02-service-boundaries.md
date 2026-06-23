# 02 — Service Boundaries

Defines the deployable units, what each owns, allowed dependencies, and the
graceful-degradation behavior the brief mandates.

## 1. The 17 logical services

| # | Service | Bounded context | Owns DB? | Tech | Scaling driver |
|---|---------|------------------|---------|------|----------------|
| 1 | **Identity** | Identity | ✅ `identity_db` | Django/DRF | auth RPS, token rotation |
| 2 | **Profile** (+Pages) | Profile & Pages | ✅ `profile_db` | Django/DRF | profile reads |
| 3 | **Social Graph** | Social Graph | ✅ `graph_db` | Django/DRF | edge writes, graph queries |
| 4 | **Post** | Posts | ✅ `post_db` | Django/DRF | write + comment volume |
| 5 | **Feed** | Feed | ✅ `feed_db` (+Redis) | Django/DRF + Celery | fan-out volume, read RPS |
| 6 | **Media** | Media | ✅ `media_db` | Django/DRF + Celery | transcode/processing |
| 7 | **Chat** | Chat | ✅ `chat_db` | Django/DRF | message volume |
| 8 | **Realtime Gateway** | Realtime | ❌ (Redis only) | Django Channels (ASGI) | concurrent sockets |
| 9 | **Notification** | Notification | ✅ `notif_db` | Django/DRF + Celery | delivery throughput |
| 10 | **Search** | Search | ❌ (OpenSearch) | Django/DRF + indexer | query RPS, indexing |
| 11 | **Marketplace** | Marketplace | ✅ `market_db` | Django/DRF | listing volume |
| 12 | **Advertisement** | Ads | ✅ `ads_db` (+Kafka later) | Django/DRF + Celery | event firehose |
| 13 | **Moderation** | Moderation | ✅ `moderation_db` | Django/DRF | queue volume |
| 14 | **Admin** | Admin | ❌ (read models + `admin_db` for flags/config) | Django/DRF | low |
| 15 | **Analytics** | Analytics | ✅ `analytics_db` (OLAP-leaning) | workers | firehose |
| 16 | **File Processing** | (part of Media) | shares `media_db` | Celery workers | CPU/GPU bound |
| 17 | **API Gateway / BFF** | — | ❌ | Traefik (edge) + thin DRF/FastAPI BFF | edge RPS |

> "Owns DB" = the only writer of that logical database. Others read via API/events.

## 2. Deployment stance: true microservices (ADR-001, accepted)

Per [ADR-001](09-decision-log.md) the user chose **true microservices**: each of
the 17 services is its **own deployable unit** — own container image, own
database, own CI/CD pipeline, own Kubernetes Deployment, and own autoscaler
(HPA). A crash loop in one service (e.g. Realtime) **cannot** exhaust another
(e.g. Post): they are separate processes with separate resource limits
(bulkheads) and separate failure domains.

The services live in a **monorepo** ([ADR-002](09-decision-log.md)) purely as a
development convenience (shared tooling, atomic contract changes, path-filtered
CI) — there is **no runtime coupling**.

**Managing the operational surface** (17 deployments is a lot): kept tractable by
— (a) **strict phasing**: services come online phase by phase (Phase 1 ships only
Identity + the foundation), never all 17 at once; (b) **Compose profiles** in
dev so you run only the services you're working on (doc 06 §2); (c) **managed
datastores** in prod; (d) each service's **Celery workers** scale independently
of its API.

> Workers note: every service that needs async work runs **its own** Celery
> worker pool (e.g. Feed fan-out, Media/File processing, Notification delivery,
> Search indexing, Analytics, Ad events) against **its own** queues — isolated,
> independently scalable, and bulkheaded from each other.

## 3. Dependency rules (the law)

1. **No shared databases.** A service may only read another context's data via
   its **REST API** or by consuming its **events** into a local read model.
2. **Async by default.** Cross-context *writes* happen through events
   (outbox → broker). Synchronous calls are allowed only for **read-time
   composition** and must be wrapped in **timeout + retry + circuit breaker**
   and have a **defined fallback**.
3. **No synchronous dependency cycles.** The sync call graph must be a DAG.
4. **Identity is the only auth authority.** Other services verify JWTs locally
   using Identity's public keys (JWKS) — no per-request call to Identity.
5. **Realtime/Search/Feed/Analytics hold derived data only.** They can be
   rebuilt from source-of-truth contexts + events.

## 4. Synchronous read dependencies (with fallbacks)

| Caller | Callee (sync read) | On callee failure → fallback |
|--------|--------------------|------------------------------|
| BFF/Feed | Profile (author display data) | serve cached author snapshot embedded in feed item |
| Feed | Social Graph (edges) | use last-known edges cached locally; eventual repair via events |
| Post | Profile (author) | cached author snapshot; render with minimal author |
| Chat | Profile (member display) | cached member snapshot |
| Marketplace | Profile (seller) | cached seller snapshot |
| BFF | Feed | show cached feed page or "retry" state |
| BFF | Search | DB-backed basic browse + category navigation |
| BFF | Ads | omit sponsored items; render organic only |

Every sync dependency above has a **read model / cache** so the caller degrades
instead of failing. This is the core of the degradation requirement.

## 5. Graceful-degradation matrix (from the brief, made explicit)

| Failing service | Still fully works | Degraded behavior | Never breaks |
|-----------------|-------------------|-------------------|--------------|
| **Chat** down | feed, profiles, pages, marketplace, notifications, search | chat shows "unavailable / reconnecting" | feed/profile/market load |
| **Marketplace** down | posts, chat, profiles, friends, feed | marketplace tab shows error state | core social flows |
| **Notification** down | every core action | events queue + retry; badge may lag | post/message/listing creation succeed |
| **Search** down | feed, profile, category browse | search box returns "temporarily unavailable" + basic browse | navigation |
| **Media processing** down | text posts, existing media | new media shows "processing / retry"; original preserved | text post creation |
| **Ads** down | organic feed & marketplace | no sponsored items shown | feed load |
| **Analytics** down | all user features | metrics/insights stale | nothing user-facing |
| **Feed** down | profile, chat, marketplace, notifications | home feed shows cached page or retry state | rest of app |
| **Realtime GW** down | all REST features | client falls back to polling; presence/typing off | data access |

## 6. Resilience primitives (where each applies)

| Primitive | Applied at |
|-----------|------------|
| **Timeouts** | every sync inter-service call + every external (storage/search/broker) call |
| **Retries + exponential backoff + jitter** | event consumers, Celery tasks, outbound webhooks/push |
| **Circuit breaker** | BFF→Feed, Feed→Graph, anything→Ads, anything→Search |
| **Bulkhead** | separate service deployments + separate Celery queues per workload (media/notif/feed/ads) |
| **Idempotency keys** | all unsafe HTTP writes (`Idempotency-Key` header) + event handlers (`event_id` dedupe) |
| **Dead-letter queue** | every async consumer; with replay tooling |
| **Health/readiness/liveness** | every service: `/healthz` (live), `/readyz` (deps), `/startupz` |
| **Rate limiting** | edge (per-IP) + per-user (Redis token bucket) + per-endpoint |
| **Feature flags** | wrap each non-core module so it can be disabled instantly |
| **Caching** | Redis read-through for hot reads; cached fallbacks for degradation |

## 7. Service-to-service authentication

- **Client → edge:** user JWT (access token), verified at BFF via JWKS.
- **Service → service (sync):** short-lived **mTLS** (in K8s) **+** signed
  internal service tokens (audience-scoped JWT minted from a shared internal
  key, NOT the user token). Internal endpoints are **never** exposed at the edge.
- **Service → broker:** per-service broker credentials (vhost/topic ACLs).

## 8. Per-service public API surface (representative — full catalog in doc 03)

- **Identity:** `/auth/*`, `/auth/sessions/*`, JWKS endpoint (internal).
- **Profile:** `/me`, `/users/{handle}`, `/pages/*`.
- **Social Graph:** `/friends/*`, `/follows/*`, `/users/{id}/block`.
- **Post:** `/posts/*`, `/comments/*`, reactions/saves/shares/reports.
- **Feed:** `/feed/*`.
- **Media:** `/media/uploads/sign`, `/media/{id}`, `/media/{id}/download-url`.
- **Chat:** `/conversations/*`, `/messages/*`.
- **Notification:** `/notifications/*`, `/devices/push-token`.
- **Marketplace:** `/marketplace/*`.
- **Ads:** `/ads/*` (advertiser-facing) + internal event ingest.
- **Search:** `/search`.
- **Moderation/Admin:** `/admin/*` (RBAC-gated).

## 9. Ownership & change rules

- Each service has a clear **owning bounded context** and a `CODEOWNERS` entry.
- Changing another context's data is done **only** by emitting an event it
  consumes, or calling its public API — never a cross-DB write or import of its
  models.
- Shared code lives in `libs/` (the shared kernel) and is versioned; changes
  there require review from all consuming services.
