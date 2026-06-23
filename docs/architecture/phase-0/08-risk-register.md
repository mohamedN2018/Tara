# 08 — Risk Register

Severity = Impact × Likelihood. Owner is the role accountable. Each risk has a
concrete mitigation already reflected in the architecture.

## 1. Top risks

| ID | Risk | Sev | Likelihood | Mitigation | Owner |
|----|------|-----|-----------|------------|-------|
| R-01 | **Ops overload from full microservices** — user chose true microservices (17 services) at 0 users → high ops cost + slower early delivery | High | High | **Accepted trade-off (user decision).** Contained via strict phasing (services arrive per phase, not all 17 now), monorepo + shared tooling, Compose profiles in dev, managed datastores in prod, and an import-linter to keep boundaries clean. | Architect |
| R-02 | **Distributed-systems complexity** (eventual consistency bugs, duplicate/lost events) | High | Med | Outbox + idempotent consumers + DLQ + contract tests; strong consistency kept within contexts. | Backend |
| R-03 | **Operational footprint too heavy for a small team** (many datastores: PG, Redis, RabbitMQ, OpenSearch, MinIO, maybe Kafka) | High | High | Compose profiles in dev; managed services in prod; OpenSearch/Kafka behind optional profiles until needed. | DevOps |
| R-04 | **Auth/token security flaws** (refresh replay, JWT mishandling, session fixation) | High | Med | Rotating refresh + family reuse detection, short access TTL, JWKS verify, Argon2id, device/session mgmt, security event log. | Security |
| R-05 | **Object-level authorization gaps** (user reads another's conversation/private media/admin data) | High | Med | Mandatory object-level perms + signed media URLs + dedicated authz test suite (E2E flow #13). | Security |
| R-06 | **Realtime scaling / state-in-socket** (one WS node holds truth; can't scale) | High | Med | Channels + Redis pub/sub; source-of-truth always in Chat/Notif; horizontal WS with sticky-less design; polling fallback. | Backend |
| R-07 | **Feed fan-out hotspots** ("celebrity" accounts blow up fan-out-on-write) | Med | Med | Hybrid fan-out: on-write for normal, on-read for high-follower; Redis hot cache; async generation. | Backend |
| R-08 | **Media pipeline failure / cost** (transcoding fails or is expensive) | Med | Med | Async processing, preserve original, `media.failed` retry state, size/type limits, queue isolation. | Backend |
| R-09 | **Event schema drift breaks consumers** | Med | Med | Versioned envelope, additive-only rule, JSON-Schema registry, consumer contract tests in CI. | Backend |
| R-10 | **PII / privacy leakage** (logs, broad events, search index) | High | Med | No secrets/bodies in logs or broad events; field-level privacy honored in read models & search; consent mgmt. | Security |
| R-11 | **Cost of managed datastores at scale** | Med | Med | Right-size, autoscale, partition + retention policies, cache aggressively, archive cold partitions. | DevOps |
| R-12 | **Scope is enormous (47 features) → never ships** | High | High | Strict phasing (P1–P9); each phase shippable; placeholders (Stories/Reels/payments) explicitly deferred. | PM/Architect |
| R-13 | **Search index divergence from source of truth** | Med | Med | Event-driven sync + periodic reconciliation/reindex job; DB fallback when Search down. | Backend |
| R-14 | **Marketplace fraud / prohibited items** | Med | Med | Moderation queue, fraud hooks, status state machine, reporting, no payments until compliance defined. | T&S |
| R-15 | **Ad event firehose overwhelms transactional broker** | Med | Med | Separate firehose (Kafka/Redpanda), dedupe + rate-limit ingest, async analytics; ads never block organic. | Backend |
| R-16 | **Single-instance dev datastores hide prod issues** (e.g. one Postgres for all DBs) | Low | High | Logical DB-per-context even in dev; document the gap; staging mirrors prod topology. | DevOps |
| R-17 | **Windows dev environment friction** (paths, line endings, Docker perf) | Low | Med | `.gitattributes` for EOL, WSL2 backend for Docker, Makefile uses cross-platform commands. | DevOps |
| R-18 | **RTL/LTR + i18n regressions** | Med | Med | RTL-first component design, logical CSS properties, i18n from day one, visual tests both directions. | Frontend |
| R-19 | **Compliance gaps** (data export, deletion, retention, consent) | Med | Med | Account deletion workflow, data export job, retention config, consent management designed in (doc 05 §6). | Security/Legal |
| R-20 | **"Done" ambiguity / false claims** (E2EE, mobile apps, payments) | Med | Low | Hard rule: never claim built unless built; placeholders labeled; see doc 00 §4. | Architect |

## 2. Decisions resolved at the Phase 0 gate (2026-06-23)

These were escalated and are now decided (see [Decision Log](09-decision-log.md)):

| Decision | Residual risk | Resolution |
|----------|---------------|------------|
| Architecture maturity | ops overload / risk of distributed monolith | **True microservices** (user) — contained per R-01 |
| Event bus | re-platforming events later | RabbitMQ first + `EventPublisher` abstraction; Kafka for firehose (ADR-003) |
| Search engine | license/cost surprise | OpenSearch (ADR-004) |
| Realtime tech | connection ceiling | Django Channels; extract Node/Go if needed (ADR-006) |

## 3. Assumptions (flag if any are wrong)

- A small team (possibly solo) builds this initially — drives ADR-001/002/003.
- Cloud-hosted production with access to managed Postgres/Redis/object storage.
- No hard launch deadline that forces skipping the phasing.
- Arabic + English are the only launch locales.
- No regulatory requirement (yet) that forbids the chosen microservices approach.

## 4. Monitoring the register

The risk register is revisited at the end of **every phase** (new risks added,
closed risks archived) as part of the standard phase report's "Risks" section.
