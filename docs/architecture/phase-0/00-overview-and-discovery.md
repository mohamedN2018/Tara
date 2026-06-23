# 00 — Overview & Discovery

## 1. Purpose of this document

This is the entry point to the **Phase 0** deliverable for **Tara**, a
production-grade social networking platform. It records what exists today,
fixes the scope and vocabulary, and links the detailed design documents.

Phase 0 produces **plans only**. No services, migrations, or application code
are created in Phase 0. Implementation starts in Phase 1, after approval.

## 2. Discovery — current repository state

Inspection performed on the working tree (`git ls-files`, full glob, file reads):

| Item | Finding |
|------|---------|
| Tracked files | `README.md`, `.gitignore` — **only two** |
| `README.md` | One line: *"Tara — A Sanskrit word meaning 'star' or 'crossing'"* |
| `.gitignore` | Standard GitHub **Python** template + extra ignores for **Celery, Redis, RabbitMQ, ActiveMQ** |
| Existing source code | **None** |
| Existing database | **None** |
| Existing services | **None** |
| Existing migrations | **None** |
| Git history | 2 commits: `Initial commit`, `Update README.md` |

### Conclusions from discovery

1. **This is a greenfield project.** There is no legacy monolith to migrate.
   The Phase 0 task "Create migration plan from existing monolith if
   applicable" is therefore **Not Applicable**. It is replaced by a
   *service-extraction / strangler-ready* strategy (document 07) so the system
   can be carved into independent services as load and team size grow.
2. **Reusable code: none.** Nothing to salvage; we design clean.
3. **Intended stack is Python/Django** (confirmed by `.gitignore` + the brief),
   with Celery + Redis + RabbitMQ already anticipated by the ignore rules.

## 3. Product scope (what we are building)

A modern social platform inspired by the **usability patterns** (not the brand,
assets, or proprietary implementation) of Facebook, Messenger, Instagram,
Marketplace, and LinkedIn. Tara is its own original identity.

Capability pillars:

- **Identity & accounts** — secure auth, sessions/devices, 2FA-ready.
- **Profiles & Pages** — rich profiles, field-level privacy, managed Pages.
- **Social graph** — friends, follows, blocks, suggestions.
- **Content** — posts (text/image/video/poll/share), reactions, comments,
  replies, shares, saved collections, hashtags, mentions.
- **Feed** — ranked + chronological fallback, cursor pagination, fan-out.
- **Media** — uploads, transcoding, thumbnails, waveforms, signed URLs, CDN.
- **Chat & real-time** — DMs, group chat, voice notes, typing, presence,
  read/delivery receipts, reactions, WebSocket gateway.
- **Marketplace** — listings, categories, search, buyer/seller chat, moderation.
- **Advertisement** — advertiser accounts, campaigns, creatives, sponsored
  placements, impression/click tracking, review workflow.
- **Notifications** — in-app, web push, push-token registration, email, prefs.
- **Search** — users, pages, posts, listings, hashtags, autocomplete.
- **Moderation & Admin** — reports, queues, actions, appeals, audit, dashboards.
- **Cross-cutting** — Arabic RTL + English LTR, light/dark themes, PWA-ready,
  mobile-ready API contracts, observability, resilience, security by design.

## 4. Non-goals for the project (explicitly out of scope until conditions met)

These are honored as **placeholders/architecture only**, never claimed as built:

- **iOS / Android apps** — not built this phase; APIs are designed to support them.
- **End-to-end encryption** — NOT implemented. Only encryption-at-rest +
  transport security are planned. E2EE is a future dedicated phase requiring
  full key management, multi-device, backup/recovery before any such claim.
- **Real payments / shipping** — placeholders only until compliance, provider,
  dispute, tax, and fraud requirements are defined.
- **AI moderation** — integration interface only; never the sole decision-maker.
- **Stories / Reels** — architecture placeholders only this cycle.

## 5. Architectural stance (summary — details in docs 02 & 09)

We build **true microservices**: each of the 17 bounded contexts is an
**independently deployable service** with its **own database**, **versioned
REST API**, **own CI/CD pipeline**, and **own scaling policy**, communicating
asynchronously via an **outbox → message broker → event bus** (and synchronous
REST only for read-time composition, behind timeout + retry + circuit breaker).
The services live in a **monorepo** — a development-time convenience with no
runtime coupling (ADR-002).

This satisfies every hard requirement in the brief from day one: per-process
fault isolation, graceful degradation, horizontal scaling, event-driven design,
and database-per-service.

> **Decided at the Phase 0 gate (2026-06-23):** the user chose microservices
> (ADR-001); the team-facing implementation choices (monorepo, RabbitMQ+Kafka,
> OpenSearch, Channels) were delegated to the architect and are recorded as
> Accepted in the [Decision Log](09-decision-log.md). The larger operational
> surface is managed via strict phasing (Phase 1 = foundation + Identity only),
> Compose profiles in dev, and managed datastores in prod.

## 6. Technology baseline (confirmed defaults; see Decision Log for the open forks)

| Concern | Choice | Notes |
|--------|--------|-------|
| Backend framework | Django + Django REST Framework | per brief & `.gitignore` |
| Real-time | Django Channels (ASGI) + Redis channel layer | uniform Python stack; extractable later |
| API style | REST under `/api/v1/`, OpenAPI via drf-spectacular | mobile-ready |
| Auth | JWT access (~15 min) + rotating refresh w/ reuse detection; Argon2id hashing | |
| Primary DB | PostgreSQL (one logical DB per context) | UUIDv7 public IDs |
| Cache / channel layer | Redis | |
| Message broker | RabbitMQ (events + Celery) initially; Kafka for the ad/analytics firehose later | ADR-003 (accepted) |
| Search | OpenSearch | Apache-2.0; ADR-004 (accepted) |
| Object storage | MinIO (dev) / S3-compatible (prod) | signed URLs, CDN-fronted |
| Background jobs | Celery workers + Celery Beat | |
| Containers / orchestration | Docker + Compose (dev), Kubernetes manifests (prod) | |
| Edge / gateway | Traefik (edge: TLS, routing, rate-limit) + thin BFF | |
| Observability | OpenTelemetry, Prometheus, Grafana, Loki, Sentry | structured JSON logs, correlation IDs |
| Frontend | Vue 3 + Vite + Pinia + Vue Router + Tailwind + Lucide | RTL/LTR, dark/light, PWA-ready |

## 7. Glossary (ubiquitous language — expanded in doc 01)

| Term | Meaning in Tara |
|------|-----------------|
| **Account** | The single central identity record per human user (UUID). |
| **Profile** | Public-facing presentation of an Account (handle, bio, photos…). |
| **Page** | An entity (business/brand/community) managed by one or more Accounts. |
| **Friendship** | A **symmetric**, mutually-accepted relationship between two Accounts. |
| **Follow** | An **asymmetric** subscription (Account→Account or Account→Page). |
| **Block** | A relationship that severs interaction/visibility between two Accounts. |
| **Post** | A unit of authored content with an audience and zero+ media. |
| **Feed** | The ranked/chronological stream of posts for a viewer. |
| **Fan-out** | Distributing a new post to followers' feeds (on-write vs on-read). |
| **Conversation** | A chat container (DM, group, marketplace, page, support). |
| **Listing** | A marketplace item for sale. |
| **Reaction** | A typed response (like/love/care/laugh/wow/sad/angry/…). |
| **Outbox** | A DB table that durably stages domain events for reliable publishing. |
| **Event** | A versioned, immutable fact published after a state change. |
| **Idempotency key** | A client-supplied token making a write safely retryable. |
| **Degradation** | A reduced but functional mode when a dependency is unavailable. |
| **Service (microservice)** | An independently-deployed runtime owning exactly one bounded context. |

## 8. What "done" means for Phase 0

- [x] Repository inspected; stack and reusable code identified.
- [x] Domain map and bounded contexts defined.
- [x] Service boundaries with sync/async dependency rules + degradation matrix.
- [x] API contract conventions + representative endpoint catalog.
- [x] Event contracts (envelope, catalog, outbox, DLQ).
- [x] Data model plan (entities, keys, indexes, partitioning).
- [x] Infrastructure plan (dev + prod + observability + CI/CD).
- [x] Migration/extraction strategy (greenfield-adapted).
- [x] Risk register.
- [x] Decision log with the forks needing your confirmation.
- [ ] **Your approval to proceed to Phase 1.** ← gate

See the [Risk Register](08-risk-register.md) and [Decision Log](09-decision-log.md)
for the items that need your input.
